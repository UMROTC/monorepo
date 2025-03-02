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
            "profession": row["profession"],  # Participant's profession (capitalized)
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
# 15. Generate a participant report for printing
# -------------------------------------------------------------------------
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

# Standardize column names by stripping extra whitespace (preserve capitalization)
participant_df.columns = participant_df.columns.str.strip()
skill_df.columns = skill_df.columns.str.strip()
gi_bill_df.columns = gi_bill_df.columns.str.strip()

print("Participant data columns:", participant_df.columns.tolist())
print("Skillset cost worksheet columns:", skill_df.columns.tolist())
print("GI Bill data columns:", gi_bill_df.columns.tolist())

# (Assume the financial model calculation has already been applied to participant_df.)
# For example:
participant_df["Net Worth Over Time"] = participant_df.apply(
    lambda row: calculate_monthly_financials(row, skill_df, gi_bill_df),
    axis=1
)

# -------------------------------------------------------------------------
# 4. Function to Generate a Pair Report
# -------------------------------------------------------------------------
def generate_pair_report(p_row, m_row):
    """
    Generates an HTML report comparing the financial model of a participant and their -mil counterpart.
    The report includes:
      - Top-right financial details from the Skillset Cost Worksheet (Profession, Average Salary, Years of School, Savings During School)
      - Two side-by-side tables showing each participant's lifestyle decisions and monthly lifestyle cost (from participant data)
      - A bar chart comparing net worth at 20 years (month 240) for the pair
    """
    # Retrieve common financial details from the Skillset Cost Worksheet for the profession.
    profession = p_row.get("Profession", "").strip()
    skill_subset = skill_df[skill_df["profession"].str.strip() == profession]
    if skill_subset.empty:
        common_info = {"Profession": "N/A", "Average Salary": "N/A", "Years of School": 0, "Savings During School": "N/A"}
    else:
        fin_row = skill_subset.iloc[0]
        try:
            months_school_val = int(fin_row.get("Months School", 0))
        except Exception:
            months_school_val = 0
        common_info = {
            "Profession": fin_row.get("Profession", "N/A"),
            "Average Salary": fin_row.get("Average Salary", "N/A"),
            "Years of School": float(months_school_val) / 12.0 if months_school_val else 0,
            "Savings During School": fin_row.get("Monthly Savings in School", "N/A")
        }

    # Retrieve lifestyle details from participant data
    p_lifestyle = {
        "Lifestyle Decisions": p_row.get("Lifestyle Decisions", "N/A"),
        "Lifestyle Cost": p_row.get("Lifestyle Cost", "N/A")
    }
    m_lifestyle = {
        "Lifestyle Decisions": m_row.get("Lifestyle Decisions", "N/A"),
        "Lifestyle Cost": m_row.get("Lifestyle Cost", "N/A")
    }

    # Extract net worth at 20 years (month 240) for both participants
    def get_networth_20(row):
        nw_list = row.get("Net Worth Over Time", [])
        if len(nw_list) >= 240:
            return nw_list[239]["Net Worth"]
        return None
    p_networth_20 = get_networth_20(p_row)
    m_networth_20 = get_networth_20(m_row)

    # Build a bar chart comparing net worth at 20 years
    chart_data = {"Name": [], "Net Worth": []}
    if p_networth_20 is not None:
        chart_data["Name"].append(p_row.get("Name", ""))
        chart_data["Net Worth"].append(p_networth_20)
    if m_networth_20 is not None:
        chart_data["Name"].append(m_row.get("Name", ""))
        chart_data["Net Worth"].append(m_networth_20)
    chart_df = pd.DataFrame(chart_data)
    chart_fig = px.bar(
        chart_df,
        x="Name",
        y="Net Worth",
        title="Net Worth Comparison at 20 Years",
        labels={"Net Worth": "Net Worth ($)", "Name": "Participant"}
    )
    chart_html = chart_fig.to_html(full_html=False, include_plotlyjs='cdn')

    # Build the HTML report with a top-right details box and side-by-side tables for lifestyle info.
    report_html = f"""
    <html>
      <head>
        <title>Financial Report: {p_row.get("Name", "")} vs. {m_row.get("Name", "")}</title>
        <style>
          body {{
            font-family: Arial, sans-serif;
            margin: 20px;
          }}
          .top-right {{
            position: absolute;
            top: 20px;
            right: 20px;
            border: 1px solid #ccc;
            padding: 10px;
            background-color: #f9f9f9;
            width: 300px;
          }}
          .lifestyle-tables {{
            display: flex;
            justify-content: space-between;
            margin-top: 200px;
          }}
          table {{
            border-collapse: collapse;
            width: 45%;
          }}
          table, th, td {{
            border: 1px solid #ccc;
          }}
          th, td {{
            padding: 8px;
            text-align: left;
          }}
          .chart-container {{
            margin-top: 50px;
            text-align: center;
          }}
        </style>
      </head>
      <body>
        <div class="top-right">
          <h2>Financial Details</h2>
          <p><strong>Profession:</strong> {common_info.get("Profession", "N/A")}</p>
          <p><strong>Average Salary:</strong> {common_info.get("Average Salary", "N/A")}</p>
          <p><strong>Years of School:</strong> {common_info.get("Years of School", 0):.1f}</p>
          <p><strong>Savings During School:</strong> {common_info.get("Savings During School", "N/A")}</p>
        </div>
        <h1>Comparison Report: {p_row.get("Name", "")} vs. {m_row.get("Name", "")}</h1>
        <div class="lifestyle-tables">
          <div>
            <h3>{p_row.get("Name", "")}'s Lifestyle</h3>
            <table>
              <tr><th>Lifestyle Decisions</th><th>Monthly Cost</th></tr>
              <tr>
                <td>{p_lifestyle.get("Lifestyle Decisions", "N/A")}</td>
                <td>{p_lifestyle.get("Lifestyle Cost", "N/A")}</td>
              </tr>
            </table>
          </div>
          <div>
            <h3>{m_row.get("Name", "")}'s Lifestyle</h3>
            <table>
              <tr><th>Lifestyle Decisions</th><th>Monthly Cost</th></tr>
              <tr>
                <td>{m_lifestyle.get("Lifestyle Decisions", "N/A")}</td>
                <td>{m_lifestyle.get("Lifestyle Cost", "N/A")}</td>
              </tr>
            </table>
          </div>
        </div>
        <div class="chart-container">
          <h3>Net Worth Comparison at 20 Years</h3>
          {chart_html}
        </div>
      </body>
    </html>
    """
    return report_html

# -------------------------------------------------------------------------
# 5. Generate Reports for Every Participant Pair
# -------------------------------------------------------------------------
# We'll loop through participant_df and for each participant whose name does not end with "-mil",
# we look for a corresponding "-mil" entry.
for index, row in participant_df.iterrows():
    name = row.get("Name", "").strip()
    # Skip if this row is already a military entry.
    if name.endswith("-mil"):
        continue
    mil_name = name + "-mil"
    mil_rows = participant_df[participant_df["Name"].str.strip() == mil_name]
    if mil_rows.empty:
        print(f"No military counterpart found for {name}. Skipping report generation.")
        continue
    mil_row = mil_rows.iloc[0]
    report_html = generate_pair_report(row, mil_row)
    if report_html:
        report_filename = f"report_{name}.html"
        report_path = current_dir / report_filename
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_html)
        print(f"Report generated for {name} and {mil_name}: {report_path}")


