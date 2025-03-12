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

# Standardize column names by stripping whitespace (preserve capitalization)
participant_df.columns = participant_df.columns.str.strip()
skill_df.columns       = skill_df.columns.str.strip()
gi_bill_df.columns     = gi_bill_df.columns.str.strip()

# Rename "profession" -> "Profession" if it exists
if "profession" in skill_df.columns:
    skill_df.rename(columns={"profession": "Profession"}, inplace=True)
if "profession" in gi_bill_df.columns:
    gi_bill_df.rename(columns={"profession": "Profession"}, inplace=True)
if "profession" in participant_df.columns:
    participant_df.rename(columns={"profession": "Profession"}, inplace=True)

print("Participant data columns:", participant_df.columns.tolist())
print("Skillset cost worksheet columns:", skill_df.columns.tolist())
print("GI Bill data columns:", gi_bill_df.columns.tolist())

# -------------------------------------------------------------------------
# 4. Calculate Monthly Net Worth
# -------------------------------------------------------------------------
def calculate_monthly_financials(row, skill_df, gi_bill_df):
    total_months = 300
    monthly_rate = (1 + 0.05) ** (1/12) - 1  # Approximately 0.00407 per month

    # Decide which financial data to use based on Military Service
    military_status = str(row.get("Military Service", "")).strip()
    loan_source = skill_df.copy() if military_status.lower() == "no" else gi_bill_df.copy()

    # Standardize profession for lookup
    original_profession = row.get("Profession", "").strip()
    profession = original_profession

    # Filter the financial data by profession
    subset = loan_source.loc[loan_source["Profession"].str.strip() == profession]
    if subset.empty:
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

    # Retrieve financial parameters
    try:
        months_school = int(loan_row.get("Months School", 0))
        monthly_in_school_savings = float(loan_row.get("Monthly Savings in School", 0.0))
        monthly_post_school_savings = float(loan_row.get("Monthly Savings", 0.0))
    except Exception as e:
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

    # For military participants, override post-school savings with participant data.
    if military_status.lower() != "no":
        try:
            monthly_post_school_savings = float(row.get("Monthly Savings", monthly_post_school_savings))
        except Exception as e:
            monthly_post_school_savings = 0.0

    # Extract monthly loan values from the financial data row
    try:
        loan_values = loan_row[[f"month {i}" for i in range(1, total_months + 1)]].astype(float).values
    except Exception as e:
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

    # Compute monthly accrued savings
    accrued_savings = []
    for m in range(1, total_months + 1):
        if months_school > 0 and m <= months_school:
            if m == 1:
                current_savings = monthly_in_school_savings
            else:
                current_savings = accrued_savings[-1] + monthly_in_school_savings
        else:
            if m == 1:
                current_savings = monthly_post_school_savings
            else:
                current_savings = accrued_savings[-1] * (1 + monthly_rate) + monthly_post_school_savings
        accrued_savings.append(current_savings)

    # Compute monthly net worth as the sum of accrued savings and the corresponding loan value
    monthly_financials = []
    for m in range(1, total_months + 1):
        idx = m - 1
        net_worth = accrued_savings[idx] + loan_values[idx]
        monthly_financials.append({
            "Month": m,
            "Accrued Savings": accrued_savings[idx],
            "Loan Value": loan_values[idx],
            "Net Worth": net_worth,
            "Profession": original_profession
        })

    return monthly_financials

# Apply the calculation function to each participant
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
            "profession": row["Profession"],
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
    color="profession",
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

# Remove Default Slider & Updatemenus from Plotly Express
fig.layout.sliders = []
fig.layout.updatemenus = []

# Define Custom Slider Steps (Yearly)
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

# Define Play/Pause Buttons
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

# Update Figure Layout with Custom Slider & Buttons
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

# Save the Figure to HTML and Display it
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
import base64
import io
from weasyprint import HTML

# Load Profession Data in Global Scope
profession_data_path = repo_root / 'app-two' / 'data' / 'input' / 'Profession_Data.csv'
try:
    profession_df = pd.read_csv(profession_data_path, encoding='utf-8-sig')
    profession_df.columns = [col.strip().lower() for col in profession_df.columns]
    # Debug output removed.
except Exception as e:
    st.error(f"Error loading Profession Data file: {e}")
    st.stop()

# Define the lifestyle columns: (Display Name, Choice Field, Cost Field)
lifestyle_columns = [
    ("Housing", "Housing Choice", "Housing Cost"),
    ("Transportation", "Transportation Choice", "Transportation Cost"),
    ("Phone", "Phone Choice", "Phone Cost"),
    ("Food", "Food Choice", "Food Cost"),
    ("Leisure", "Leisure Choice", "Leisure Cost"),
    ("Common Interests", "Common Interest Choice", "Common Interest Cost"),
    ("Children", "Number of Children", "Children Cost"),
    ("Who Pays for College", "Who pays for College", ""),
    ("Health Insurance", "Health Insurance Level", "Health Insurance Cost"),
    ("Monthly Savings", "Savings Choice", "Monthly Savings"),
]

# --- Helper Functions ---
def format_as_dollars(value):
    """Convert a numeric value into a dollar-formatted string."""
    try:
        val_float = float(str(value).replace(",", "").strip())
        return f"${val_float:,.2f}"
    except Exception:
        return str(value)

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
    try:
        school_cost_val = float(school_cost)
        school_cost = f"${school_cost_val:,.0f}"
    except Exception:
        pass
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
    """Return the net worth for a participant at the specified month (1-indexed)."""
    nw_list = row.get("Net Worth Over Time", [])
    if len(nw_list) >= month:
        return nw_list[month - 1]["Net Worth"]
    return None

def get_chart_image(chart_fig):
    """
    Renders the Plotly figure to a PNG image using kaleido,
    encodes it in base64, and returns an HTML <img> tag.
    """
    try:
        img_bytes = chart_fig.to_image(format="png")
        encoded = base64.b64encode(img_bytes).decode("utf-8")
        return (
            f'<img src="data:image/png;base64,{encoded}" '
            f'alt="Net Worth Chart" '
            f'style="max-width:78%; float:right; margin-left:auto; margin-right:0;" />'
        )
    except Exception as e:
        st.error(f"Error generating chart image: {e}")
        return "<p>Error generating chart image.</p>"

def build_lifestyle_table(c_row):
    """
    Builds an HTML table with columns for each lifestyle category,
    including cell borders and cost values formatted as dollars.
    """
    table_html = f"""
    <table style="width:100%; border-collapse: collapse;" border="1">
      <thead>
        <tr style="background-color:#e1e1e1; font-size:10px;">
          <th></th>
    """
    for display_name, _, _ in lifestyle_columns:
        table_html += f"<th>{display_name}</th>"
    table_html += "</tr></thead><tbody style='font-size:10px;'>"
    table_html += f"<tr><td>Choice</td>"
    for _, choice_field, _ in lifestyle_columns:
        choice_val = c_row.get(choice_field, "N/A")
        table_html += f"<td>{choice_val}</td>"
    table_html += "</tr>"
    table_html += f"<tr><td>Cost</td>"
    for _, _, cost_field in lifestyle_columns:
        if cost_field:
            cost_val = c_row.get(cost_field, "N/A")
            cost_val = format_as_dollars(cost_val)
        else:
            cost_val = ""
        table_html += f"<td>{cost_val}</td>"
    table_html += "</tr>"
    table_html += "</tbody></table>"
    return table_html

# --- Report Generation Functions ---
def generate_pair_report(c_row, m_row):
    """
    Generates an HTML report for a civilian (c_row) and military (m_row) participant pair.
    Layout:
      - Title: "(Participant's Name)'s Financial Projection" (centered)
      - Professional details (left-aligned)
      - A net worth chart (static image) aligned to the right
      - Profession descriptions for civilian and military with horizontal rules,
      - A two-row lifestyle table for the civilian participant with a title immediately above it for "Summary of Lifestyle Choices"
      - A note at the bottom of the page
    """
    global profession_df
    common_info = get_common_info(c_row, skill_df)
    profession = c_row.get("Profession", "").strip()
    prof_match = profession_df[profession_df["profession"].str.strip().str.lower() == profession.lower()]
    if not prof_match.empty:
        prof_row = prof_match.iloc[0]
        civilian_desc = prof_row.get("description", "Description not available.")
        military_desc = prof_row.get("military equivalent", "Description not available.")
    else:
        civilian_desc = "Description not available."
        military_desc = "Description not available."
    years = [2024, 2035, 2045]
    c_values = [get_networth_at(c_row, 1), get_networth_at(c_row, 120), get_networth_at(c_row, 240)]
    m_values = [get_networth_at(m_row, 1), get_networth_at(m_row, 120), get_networth_at(m_row, 240)]
    chart_fig = px.line(
        x=years,
        y=c_values,
        markers=True,
        title="Simple Net Worth Over Time",
        labels={"x": "Year", "y": "Net Worth ($)"}
    )
    chart_fig.data[0].line.dash = 'dot'
    chart_fig.data[0].name = f"{c_row.get('Name', 'Civilian')}"
    chart_fig.data[0].showlegend = True
    chart_fig.add_scatter(
        x=years,
        y=m_values,
        mode="lines+markers",
        name=f"{m_row.get('Name', 'Military')}",
        line=dict(dash='solid')
    )
    chart_fig.data[1].showlegend = True
    min_val = min([v for v in c_values + m_values if v is not None], default=0)
    max_val = max([v for v in c_values + m_values if v is not None], default=0)
    chart_fig.update_yaxes(range=[min_val - 50000, max_val + 50000])
    chart_html = get_chart_image(chart_fig)
    lifestyle_table_html = build_lifestyle_table(c_row)
    name_str = c_row.get("Name", "Participant")
    note_text = (
        "This sheet depicts a simple net worth calculation that considers only two values - your monthly savings "
        "compounding at 5% Annually, and your student debt, compounding at 6% Annually. The decisions that you made in the Budget Simulator program are displayed at the bottom, along with their associated costs. "
        "The intent of this sheet is to give you the ability to project how student debt will affect your purchase power in the future. Scholarships and grants are great ways to payfor training you will need "
        "in your future profession. The Military is one of many employers who will help pay for your training and education for your job. If you go straight to work after graduation, the cost associated with "
        "that profession represents licensing, tools, and apprenticeships (if any)."
    )
    report_html = f"""
    <html>
      <head>
        <meta charset="utf-8">
        <title>{name_str}'s Financial Projection</title>
        <style>
          body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            font-size: 12px;
          }}
          .header {{
            text-align: center;
            margin-bottom: 10px;
          }}
          .header h1 {{
            margin: 0;
            font-size: 20px;
          }}
          .professional-details {{
            margin-bottom: 10px;
            font-size: 11px;
          }}
          /* Chart section remains unchanged */
          .chart-section {{
            margin-top: -1.0in;
          }}
          /* Description section: move text columns down an extra 1.5" by setting top margin to 2.75in */
          .description-section {{
            margin-top: 1.80in;
            font-size: 11px;
            padding-bottom: 5px;
          }}
          .description-section h3 {{
            margin-bottom: 5px;
            font-size: 12px;
          }}
          .description-section hr {{
            margin-bottom: 5px;
          }}
          /* Lifestyle section: move table up with a -0.75in top margin */
          .lifestyle-section {{
            margin-top: -0.75in;
            font-size: 11px;
          }}
          .lifestyle-title {{
            text-align: center;
            font-size: 12px;
            margin: 0;
            padding-bottom: 5px;
          }}
          table {{
            margin-top: 0;
            border-collapse: collapse;
          }}
          th, td {{
            padding: 4px 6px;
            text-align: center;
            border: 1px solid #000;
            font-size: 10px;
          }}
          .note-section {{
            margin-top: 10px;
            font-size: 10px;
            text-align: left;
            border-top: 1px solid #000;
            padding-top: 5px;
          }}
        </style>
      </head>
      <body>
        <div class="header">
          <h1>{name_str}'s Financial Projection</h1>
        </div>
        <div class="professional-details">
          <p><strong>Profession:</strong> {common_info.get("Profession")}</p>
          <p><strong>Annual Salary:</strong> {common_info.get("Average Salary")}</p>
          <p><strong>Years of School:</strong> {common_info.get("Years of School")}</p>
          <p><strong>Average Cost of School:</strong> {common_info.get("School Cost")}</p>
        </div>
        <div class="chart-section">
          {chart_html}
        </div>
        <div class="description-section">
          <h3>Profession Description</h3>
          <hr />
          <p>{civilian_desc}</p>
          <h3>Military Equivalent</h3>
          <hr />
          <p>{military_desc}</p>
        </div>
        <div class="lifestyle-section">
          <div class="lifestyle-title">
            <h3>Summary of Lifestyle Choices</h3>
          </div>
          {lifestyle_table_html}
        </div>
        <div class="note-section">
          <p>{note_text}</p>
        </div>
      </body>
    </html>
    """
    return report_html

def generate_combined_pdf_report(report_html_list, pdf_output_path):
    """
    Combines a list of HTML report strings into a single PDF file in landscape orientation.
    Each report is separated by a page break.
    """
    combined_html = """
    <html>
      <head>
         <meta charset="utf-8">
         <style>
           @page { size: A4 landscape; margin: 1cm; }
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

# --- Main Loop: Generate Reports ---
all_reports = []
for index, row in participant_df.iterrows():
    name = row.get("Name", "").strip()
    if name.endswith("-mil"):
        continue
    mil_name = name + "-mil"
    mil_rows = participant_df[participant_df["Name"].str.strip() == mil_name]
    if mil_rows.empty:
        continue
    mil_row = mil_rows.iloc[0]
    report_html = generate_pair_report(row, mil_row)
    all_reports.append(report_html)
    
pdf_output_path = current_dir.parent / "data" / "output" / "combined_reports.pdf"
generate_combined_pdf_report(all_reports, pdf_output_path)

st.write(f"Combined PDF report generated at: {pdf_output_path}")

