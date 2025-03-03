import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import os
import json
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials

# -------------------------------------------------------------------------
# 1. Google Permissions
# -------------------------------------------------------------------------
SHEET_KEY = "1rgS_NxsZjDkPE07kEpuYxvwktyROXKUfYBk-4t9bkqA"
SHEET_NAME = "participant_data"
CREDENTIALS_PATH = Path("C:/Users/Jack Helmsing/Documents/Helmsing Army Documents/Recruiting/gitignore/atomic-monument-448919-i5-8043c996fb0e.json")

def authorize_gspread():
    """
    Authorize gspread client with loaded credentials.
    """
    try:
        creds = Credentials.from_service_account_file(
            CREDENTIALS_PATH,
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
        )
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Error authorizing gspread client: {e}")
        st.stop()

def get_google_sheet(client, sheet_key, worksheet_name="participant_data"):
    """
    Access a specific worksheet in the Google Sheet.
    """
    try:
        sheet = client.open_by_key(sheet_key)
        worksheet = sheet.worksheet(worksheet_name)
        data = worksheet.get_all_records(expected_headers=worksheet.row_values(1))
        return pd.DataFrame(data)
    except gspread.SpreadsheetNotFound:
        st.error("Google Sheet not found. Please check the SHEET_KEY.")
        st.stop()
    except gspread.WorksheetNotFound:
        st.error(f"Worksheet '{worksheet_name}' not found in the Google Sheet.")
        st.stop()
    except Exception as e:
        st.error(f"Error accessing Google Sheet: {e}")
        st.stop()

# -------------------------------------------------------------------------
# 2. File Paths
# -------------------------------------------------------------------------
current_dir = Path(__file__).parent.resolve()
repo_root = current_dir.parent.parent

skillset_cost_worksheet_path = repo_root / 'app-one' / 'data' / 'input' / 'Skillset_cost_worksheet_CSV.csv'
gi_bill_path = repo_root / 'app-two' / 'data' / 'input' / 'GI_Bill_Application.csv'

try:
    gi_bill_df = pd.read_csv(gi_bill_path)
except FileNotFoundError as e:
    print(f"GI Bill reference sheet not found: {e}")
    exit()
except Exception as e:
    print(f"Error loading GI Bill reference sheet: {e}")
    exit()

output_csv_path = current_dir.parent / "data" / "output" / "financial_model_plot.csv"
output_html_path = current_dir.parent / "data" / "output" / "plotly_bar_chart_race.html"

# -------------------------------------------------------------------------
# 3. Load Participant and Financial Data Separately (Approach 1)
# -------------------------------------------------------------------------
client = authorize_gspread()
participant_df = get_google_sheet(client, SHEET_KEY, SHEET_NAME)
if participant_df.empty:
    st.warning("🚨 No participant data found! Please have participants fill out their surveys first.")
    st.stop()

try:
    skill_df = pd.read_csv(skillset_cost_worksheet_path)
except FileNotFoundError as e:
    print(f"File not found: {e}")
    exit()
except Exception as e:
    print(f"Error loading files: {e}")
    exit()

# 1. Standardize column names by stripping whitespace (preserve capitalization)
participant_df.columns = participant_df.columns.str.strip()
skill_df.columns       = skill_df.columns.str.strip()
gi_bill_df.columns     = gi_bill_df.columns.str.strip()

# 2. Rename "profession" -> "Profession" in skill_df, gi_bill_df, participant_df if it exists
if "profession" in skill_df.columns:
    skill_df.rename(columns={"profession": "Profession"}, inplace=True)
if "profession" in gi_bill_df.columns:
    gi_bill_df.rename(columns={"profession": "Profession"}, inplace=True)
if "profession" in participant_df.columns:
    participant_df.rename(columns={"profession": "Profession"}, inplace=True)

print("Participant data columns:", participant_df.columns.tolist())
print("Skillset cost worksheet columns:", skill_df.columns.tolist())
print("GI Bill data columns:", gi_bill_df.columns.tolist())

# 3. Optional debug loop: Check if each participant's Profession exists in the appropriate financial data
for i, row in participant_df.iterrows():
    ms = str(row.get("Military Service", "")).strip()
    # Decide which sheet to match
    if ms.lower() == "no":
        loan_source = skill_df
    else:
        loan_source = gi_bill_df

    # Extract the participant's Profession (capitalized column now)
    prof = str(row.get("Profession", "")).strip()

    # Compare with "Profession" in loan_source
    matching = loan_source.loc[loan_source["Profession"].str.strip() == prof]
    if matching.empty:
        print(f"[DEBUG] Row={i}, Name='{row.get('Name')}', Profession='{row.get('Profession')}'"
              f" => NOT FOUND in {'skill_df' if ms.lower()=='no' else 'gi_bill_df'}")

# -------------------------------------------------------------------------
# 4. Calculate Monthly Net Worth
# -------------------------------------------------------------------------
def calculate_monthly_financials(row, skill_df, gi_bill_df):
    total_months = 300
    monthly_rate = (1 + 0.05) ** (1/12) - 1  # Approximately 0.00407 per month

    # 1) Decide which financial data to use based on Military Service
    military_status = str(row.get("Military Service", "")).strip()
    if military_status.lower() == "no":
        loan_source = skill_df.copy()
    else:
        loan_source = gi_bill_df.copy()

    # 2) Save the original profession (for display) and standardize for lookup (only stripping whitespace)
    original_profession = row.get("Profession", "").strip()
    loan_source.columns = loan_source.columns.str.strip()  # Preserve capitalization
    # For matching, we use the exact string after stripping extra whitespace
    profession = original_profession

    # 3) Filter the financial data by profession
    subset = loan_source.loc[loan_source["Profession"].str.strip() == profession]
    if subset.empty:
        print(f"[DEBUG] Profession '{profession}' not found in the selected loan source.")
        default_financials = []
        for m in range(1, total_months + 1):
            default_financials.append({
                "Month": m,
                "Accrued Savings": 0,
                "Loan Value": 0,
                "Net Worth": 0,
                "Profession": original_profession
            })
        return default_financials
    loan_row = subset.iloc[0]

    # 4) Retrieve financial parameters from the financial data row
    try:
        # For non-military participants, these values come from the CSV.
        # For military participants, the in-school values still come from CSV,
        # but the post-school savings will be overridden with participant data.
        months_school = int(loan_row.get("Months School", 0))
        monthly_in_school_savings = float(loan_row.get("Monthly Savings in School", 0.0))
        monthly_post_school_savings = float(loan_row.get("Monthly Savings", 0.0))
    except Exception as e:
        print(f"[DEBUG] Error reading financial parameters for profession '{profession}': {e}")
        default_financials = []
        for m in range(1, total_months + 1):
            default_financials.append({
                "Month": m,
                "Accrued Savings": 0,
                "Loan Value": 0,
                "Net Worth": 0,
                "Profession": original_profession
            })
        return default_financials

    # 5) For military participants, override the after-school savings value with the one from Participant Data.
    if military_status.lower() != "no":
        try:
            # Override post-school savings with the value in the participant data.
            monthly_post_school_savings = float(row.get("Monthly Savings", monthly_post_school_savings))
        except Exception as e:
            print(f"[DEBUG] Error reading participant after-school savings for profession '{profession}': {e}")
            monthly_post_school_savings = 0.0

    # 6) Extract monthly loan values from the financial data row
    try:
        loan_values = loan_row[[f"month {i}" for i in range(1, total_months + 1)]].astype(float).values
    except Exception as e:
        print(f"[DEBUG] Error extracting loan values for profession '{profession}': {e}")
        default_financials = []
        for m in range(1, total_months + 1):
            default_financials.append({
                "Month": m,
                "Accrued Savings": 0,
                "Loan Value": 0,
                "Net Worth": 0,
                "Profession": original_profession
            })
        return default_financials

    # 7) Compute monthly accrued savings with the proper timing:
    accrued_savings = []
    for m in range(1, total_months + 1):
        if months_school > 0 and m <= months_school:
            # In-school period: add only the in-school savings (no compounding)
            if m == 1:
                current_savings = monthly_in_school_savings
            else:
                current_savings = accrued_savings[-1] + monthly_in_school_savings
            print(f"Month {m}: IN-SCHOOL. Added {monthly_in_school_savings}; Total Savings: {current_savings}")
        else:
            # Post-school period: compound previous savings and add post-school savings
            if m == 1:
                # This case occurs if months_school is 0.
                current_savings = monthly_post_school_savings
            else:
                current_savings = accrued_savings[-1] * (1 + monthly_rate) + monthly_post_school_savings
            print(f"Month {m}: POST-SCHOOL. Added {monthly_post_school_savings}; Total Savings: {current_savings}")
        accrued_savings.append(current_savings)

    # 8) Compute monthly net worth as the sum of accrued savings and the corresponding loan value
    monthly_financials = []
    for m in range(1, total_months + 1):
        idx = m - 1
        net_worth = accrued_savings[idx] + loan_values[idx]
        monthly_financials.append({
            "Month": m,
            "Accrued Savings": accrued_savings[idx],
            "Loan Value": loan_values[idx],
            "Net Worth": net_worth,
            "Profession": original_profession  # Preserve original capitalization for display
        })

    return monthly_financials

# Apply the calculation function to each participant (using participant_df)
participant_df["Net Worth Over Time"] = participant_df.apply(
    lambda row: calculate_monthly_financials(row, skill_df, gi_bill_df),
    axis=1
)

# -------------------------------------------------------------------------
# 5. (Optional) Fill Missing Columns in participant_df if needed
# -------------------------------------------------------------------------
for col in ['Months School', 'Monthly Savings in School', 'Monthly Savings']:
    if col in participant_df.columns:
        participant_df[col] = participant_df[col].fillna(0)

# -------------------------------------------------------------------------
# 7. Expand to Long Format for Plotting and CSV output
# -------------------------------------------------------------------------
expanded_rows = []
for _, row in participant_df.iterrows():
    for record in row["Net Worth Over Time"]:
        expanded_rows.append({
            "Name": row["Name"],
            "profession": row["Profession"],  # Participant's profession (capitalized)
            "Month": record["Month"],
            "Savings Balance": record["Accrued Savings"],
            "Loan Balance": record["Loan Value"],
            "Net Worth": record["Net Worth"],
            "ProfessionDisplay": record["Profession"]
        })

expanded_df = pd.DataFrame(expanded_rows)

# -------------------------------------------------------------------------
# 8. Accounting-Style Label for Net Worth
# -------------------------------------------------------------------------
expanded_df['Net Worth Label'] = expanded_df['Net Worth'].apply(
    lambda x: f"(${abs(x):,.2f})" if x < 0 else f"${x:,.2f}"
)

# -------------------------------------------------------------------------
# 9. Save Expanded Data to CSV
# -------------------------------------------------------------------------
try:
    expanded_df.to_csv(output_csv_path, index=False)
    print(f"Monthly data saved to CSV at: {output_csv_path}")
except Exception as e:
    print("Error saving CSV:", e)

# -------------------------------------------------------------------------
# 10. Create Animated Bar Chart Figure using Plotly
# -------------------------------------------------------------------------
fig = px.bar(
    expanded_df,
    x="Net Worth",
    y="Name",
    orientation="h",
    color="profession",  # Use the capitalized profession for color grouping
    animation_frame="Month",
    text="Net Worth Label",
    title="Net Worth Over 25 Years - Yearly Slider & Pause Fix",
    labels={
        "Net Worth": "Net Worth ($)",
        "Name": "Participants",
        "profession": "Career"
    },
    color_discrete_sequence=px.colors.qualitative.Set2
)
fig.update_traces(textposition="outside", cliponaxis=False)

# -------------------------------------------------------------------------
# Remove Default Slider & Updatemenus from Plotly Express
# -------------------------------------------------------------------------
fig.layout.sliders = []
fig.layout.updatemenus = []

# -------------------------------------------------------------------------
# 11. Define Custom Slider Steps (Yearly)
# -------------------------------------------------------------------------
slider_steps = []
for year in range(1, 26):
    final_month = year * 12
    slider_steps.append(dict(
        method="animate",
        label=f"Year {year}",
        args=[[f"{final_month}"],
              {"mode": "immediate",
               "frame": {"duration": 500, "redraw": True},
               "transition": {"duration": 0}}
             ]
    ))
custom_slider = dict(
    active=0,
    steps=slider_steps,
    x=0.1,
    y=-0.3,
    len=0.8,
    xanchor="left",
    yanchor="bottom",
    pad={"t": 50, "b": 10},
    currentvalue={"prefix": "Jump to: "}
)

# -------------------------------------------------------------------------
# 12. Define Play/Pause Buttons
# -------------------------------------------------------------------------
play_pause_menu = dict(
    type="buttons",
    direction="left",
    x=0.1,
    y=-0.4,
    buttons=[
        dict(
            label="Play",
            method="animate",
            args=[None, {"frame": {"duration": 300, "redraw": True},
                         "transition": {"duration": 0},
                         "fromcurrent": True}],
        ),
        dict(
            label="Pause",
            method="animate",
            args=[[None], {"mode": "immediate",
                           "frame": {"duration": 0, "redraw": False},
                           "transition": {"duration": 0}}],
        ),
    ]
)

# -------------------------------------------------------------------------
# 13. Update Figure Layout with Custom Slider & Buttons
# -------------------------------------------------------------------------
fig.update_layout(
    title=dict(
        text="Net Worth Over Time",
        x=0.5,
        y=0.95,
        xanchor="center",
        yanchor="top",
        font=dict(size=24, color="black")
    ),
    font=dict(color='black'),
    xaxis=dict(tickfont=dict(color='black')),
    yaxis=dict(tickfont=dict(color='black')),
    plot_bgcolor='white',
    paper_bgcolor='white',
    sliders=[custom_slider],
    updatemenus=[play_pause_menu],
    margin=dict(l=50, r=50, t=50, b=200),
    height=900,
    legend=dict(
        title="Career",
        x=1.05,
        y=1,
        bgcolor="Black",
        bordercolor="White",
        borderwidth=1,
    ),
)

# -------------------------------------------------------------------------
# 14. Save the Figure to HTML and Display it
# -------------------------------------------------------------------------
try:
    fig.write_html(output_html_path)
    print(f"Bar chart saved to HTML at: {output_html_path}")
except Exception as e:
    print("Error saving HTML file:", e)

st.plotly_chart(fig)

print("Script complete.")

# -------------------------------------------------------------------------
# PDF Report Generation Section (Appended)
# -------------------------------------------------------------------------
from weasyprint import HTML  # for PDF conversion

# Load Profession Data (for job descriptions)
profession_data_path = repo_root / 'app-two' / 'data' / 'input' / 'Profession_Data.csv'
try:
    # Use utf-8-sig to handle BOM characters
    profession_df = pd.read_csv(profession_data_path, encoding='utf-8-sig')
    # Normalize column names: strip whitespace and convert to lowercase.
    profession_df.columns = [col.strip().lower() for col in profession_df.columns]
    st.write("Profession Data columns:", profession_df.columns.tolist())
except Exception as e:
    st.error(f"Error loading Profession Data file: {e}")
    st.stop()


def get_common_info(row, skill_df):
    """Extract professional details from skill_df for a given participant row."""
    profession = row.get("Profession", "").strip()
    skill_subset = skill_df[skill_df["Profession"].str.strip() == profession]
    if skill_subset.empty:
        return {"Profession": "N/A", "Average Salary": "N/A", "Years of School": "N/A", "School Cost": "N/A"}
    fin_row = skill_subset.iloc[0]
    try:
        months_school_val = int(fin_row.get("Months School", 0))
    except Exception:
        months_school_val = 0
    school_cost = fin_row.get("School Cost", "N/A")
    avg_salary = fin_row.get("Average Salary", "N/A")
    try:
        avg_salary = float(avg_salary)
        avg_salary = f"${avg_salary:,.0f}"
    except Exception:
        pass
    return {
        "Profession": fin_row.get("Profession", "N/A"),
        "Average Salary": avg_salary,
        "Years of School": f"{float(months_school_val)/12:.1f}" if months_school_val else "N/A",
        "School Cost": school_cost
    }

def get_networth_at(row, month):
    """Helper: Return the net worth for a participant at the specified month (1-indexed)."""
    nw_list = row.get("Net Worth Over Time", [])
    if len(nw_list) >= month:
        return nw_list[month - 1]["Net Worth"]
    return None

def generate_pair_report(c_row, m_row):
    """
    Generates an HTML report for a civilian (c_row) and military (m_row) participant pair.
    Layout based on the provided PDF:
      - Header with professional details from Skillset_cost_worksheet_csv.
      - A net worth chart using values at 2025 (month 1), 2035 (month 120), and 2045 (month 240) for both participants.
      - Profession description (civilian) and military counterpart roles from Profession_Data.
      - A table with lifestyle decisions and costs displayed along the bottom of the page.
    """
    # Retrieve professional details from skill_df (for the civilian row)
    common_info = get_common_info(c_row, skill_df)
    
    # Retrieve job descriptions from Profession_Data (match by Profession)
    profession = c_row.get("Profession", "").strip()
    prof_match = profession_df[profession_df["profession"].str.strip().str.lower() == profession.lower()]
    if not prof_match.empty:
        prof_row = prof_match.iloc[0]
        civilian_desc = prof_row.get("description", "Description not available.")
        military_desc = prof_row.get("military equivalent", "Description not available.")
    else:
        civilian_desc = "Description not available."
        military_desc = "Description not available."
    
    # Retrieve lifestyle details (assume columns "Lifestyle Decisions" and "Lifestyle Cost")
    c_lifestyle = {
        "Lifestyle Decisions": c_row.get("Lifestyle Decisions", "N/A"),
        "Lifestyle Cost": c_row.get("Lifestyle Cost", "N/A")
    }
    m_lifestyle = {
        "Lifestyle Decisions": m_row.get("Lifestyle Decisions", "N/A"),
        "Lifestyle Cost": m_row.get("Lifestyle Cost", "N/A")
    }
    
    # Create a table (HTML) for Lifestyle Summary
    lifestyle_table_html = f"""
    <table style="width:100%; border-collapse: collapse;" border="1">
      <tr>
        <th>Participant</th>
        <th>Lifestyle Decisions</th>
        <th>Monthly Cost</th>
      </tr>
      <tr>
        <td>{c_row.get("Name", "")}</td>
        <td>{c_lifestyle.get("Lifestyle Decisions")}</td>
        <td>{c_lifestyle.get("Lifestyle Cost")}</td>
      </tr>
      <tr>
        <td>{m_row.get("Name", "")}</td>
        <td>{m_lifestyle.get("Lifestyle Decisions")}</td>
        <td>{m_lifestyle.get("Lifestyle Cost")}</td>
      </tr>
    </table>
    """
    
    # Build a net worth line chart using Plotly for 2025, 2035, and 2045.
    years = [2025, 2035, 2045]
    c_values = [get_networth_at(c_row, 1), get_networth_at(c_row, 120), get_networth_at(c_row, 240)]
    m_values = [get_networth_at(m_row, 1), get_networth_at(m_row, 120), get_networth_at(m_row, 240)]
    
    chart_fig = px.line(
        x=years,
        y=c_values,
        markers=True,
        title="Simple Net Worth Over Time",
        labels={"x": "Year", "y": "Net Worth ($)"}
    )
    chart_fig.add_scatter(x=years, y=m_values, mode="lines+markers", name=m_row.get("Name", ""))
    min_val = min([v for v in c_values + m_values if v is not None], default=0)
    max_val = max([v for v in c_values + m_values if v is not None], default=0)
    chart_fig.update_yaxes(range=[min_val - 50000, max_val + 50000])
    chart_html = chart_fig.to_html(full_html=False, include_plotlyjs='cdn')
    
    # Build the HTML report string with the lifestyle table at the bottom.
    report_html = f"""
    <html>
      <head>
        <meta charset="utf-8">
        <title>Financial Projection Summary: {c_row.get("Name", "")} vs. {m_row.get("Name", "")}</title>
        <style>
          body {{
            font-family: Arial, sans-serif;
            margin: 20px;
          }}
          .header {{
            text-align: center;
            margin-bottom: 20px;
          }}
          .header h1 {{
            margin: 0;
            font-size: 24px;
          }}
          .header h2 {{
            margin: 5px 0;
            font-size: 18px;
          }}
          .professional-details {{
            text-align: center;
            margin-bottom: 20px;
          }}
          .professional-details p {{
            margin: 2px;
            font-size: 14px;
          }}
          .chart-section {{
            margin-bottom: 20px;
          }}
          .description-section {{
            margin-top: 30px;
            font-size: 12px;
            margin-bottom: 20px;
          }}
          .description-section h3 {{
            margin-bottom: 5px;
          }}
          .lifestyle-section {{
            margin-top: 30px;
            font-size: 12px;
            text-align: center;
          }}
        </style>
      </head>
      <body>
        <!-- Header with Professional Details -->
        <div class="header">
          <h1>{common_info.get("Profession")}</h1>
          <h2>Annual Salary: {common_info.get("Average Salary")}</h2>
        </div>
        <div class="professional-details">
          <p>Years of School: {common_info.get("Years of School")}</p>
          <p>Average Cost of School: {common_info.get("School Cost")}</p>
        </div>
        <!-- Net Worth Chart -->
        <div class="chart-section">
          {chart_html}
        </div>
        <!-- Profession Description -->
        <div class="description-section">
          <h3>Profession Description</h3>
          <p>{civilian_desc}</p>
          <h3>Military Equivalent</h3>
          <p>{military_desc}</p>
        </div>
        <!-- Lifestyle Summary Table at the Bottom -->
        <div class="lifestyle-section">
          <h3>Summary of Lifestyle Choices</h3>
          {lifestyle_table_html}
        </div>
      </body>
    </html>
    """
    return report_html


def generate_combined_pdf_report(report_html_list, pdf_output_path):
    """
    Combines a list of HTML report strings into a single PDF file.
    Each report is separated by a page break.
    """
    combined_html = """
    <html>
      <head>
         <meta charset="utf-8">
         <style>
           @page { size: A4; margin: 1cm; }
           .page-break { page-break-after: always; }
         </style>
      </head>
      <body>
    """
    for report in report_html_list:
        combined_html += report + '<div class="page-break"></div>'
    combined_html += "</body></html>"
    
    HTML(string=combined_html).write_pdf(str(pdf_output_path))
    print(f"Combined PDF report saved to: {pdf_output_path}")

# Loop through participant_df to generate reports for each valid participant pair.
all_reports = []
for index, row in participant_df.iterrows():
    name = row.get("Name", "").strip()
    # Skip if this row is already a military entry (assuming naming convention ends with "-mil")
    if name.endswith("-mil"):
        continue
    mil_name = name + "-mil"
    mil_rows = participant_df[participant_df["Name"].str.strip() == mil_name]
    if mil_rows.empty:
        print(f"No military counterpart found for {name}. Skipping report generation for this pair.")
        continue
    mil_row = mil_rows.iloc[0]
    report_html = generate_pair_report(row, mil_row)
    all_reports.append(report_html)
    # Optionally, save individual HTML files for debugging:
    # individual_report_path = current_dir / f"report_{name}.html"
    # with open(individual_report_path, "w", encoding="utf-8") as f:
    #     f.write(report_html)
    # print(f"Generated report for {name} and {mil_name}: {individual_report_path}")

# Define the PDF output path (same output folder as before)
pdf_output_path = current_dir.parent / "data" / "output" / "combined_reports.pdf"
generate_combined_pdf_report(all_reports, pdf_output_path)

st.write(f"Combined PDF report generated at: {pdf_output_path}")


