import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
import json
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials
from weasyprint import HTML  # for PDF conversion

# -------------------------------------------------------------------------
# 1. Google Permissions and Data Loading Functions
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
# 2. Define File Paths and Load Reference Files
# -------------------------------------------------------------------------
current_dir = Path(__file__).parent.resolve()
repo_root = current_dir.parent.parent

skillset_cost_worksheet_path = repo_root / 'app-one' / 'data' / 'input' / 'Skillset_cost_worksheet_CSV.csv'
gi_bill_path = repo_root / 'app-two' / 'data' / 'input' / 'GI_Bill_Application.csv'
profession_data_path = repo_root / 'app-two' / 'data' / 'input' / 'Profession Data.csv'

# Load GI Bill and Profession Data files
try:
    gi_bill_df = pd.read_csv(gi_bill_path)
except Exception as e:
    st.error(f"Error loading GI Bill reference sheet: {e}")
    st.stop()

try:
    profession_df = pd.read_csv(profession_data_path)
except Exception as e:
    st.error(f"Error loading Profession Data file: {e}")
    st.stop()

# -------------------------------------------------------------------------
# 3. Load Participant Data and Skillset Cost Worksheet
# -------------------------------------------------------------------------
client = authorize_gspread()
participant_df = get_google_sheet(client, SHEET_KEY, SHEET_NAME)
if participant_df.empty:
    st.warning("🚨 No participant data found! Please have participants fill out their surveys first.")
    st.stop()

try:
    skill_df = pd.read_csv(skillset_cost_worksheet_path)
except Exception as e:
    st.error(f"Error loading Skillset Cost Worksheet: {e}")
    st.stop()

# Standardize column names by stripping whitespace
participant_df.columns = participant_df.columns.str.strip()
skill_df.columns = skill_df.columns.str.strip()
gi_bill_df.columns = gi_bill_df.columns.str.strip()
profession_df.columns = profession_df.columns.str.strip()

# Rename "profession" to "Profession" if present
for df in [participant_df, skill_df, gi_bill_df]:
    if "profession" in df.columns:
        df.rename(columns={"profession": "Profession"}, inplace=True)

# Optional: Debug log of column names
print("Participant data columns:", participant_df.columns.tolist())
print("Skillset cost worksheet columns:", skill_df.columns.tolist())
print("GI Bill data columns:", gi_bill_df.columns.tolist())
print("Profession Data columns:", profession_df.columns.tolist())

# -------------------------------------------------------------------------
# 4. Calculate Monthly Net Worth (Existing Function)
# -------------------------------------------------------------------------
def calculate_monthly_financials(row, skill_df, gi_bill_df):
    total_months = 300
    monthly_rate = (1 + 0.05) ** (1/12) - 1  # Approximately 0.00407 per month

    military_status = str(row.get("Military Service", "")).strip()
    if military_status.lower() == "no":
        loan_source = skill_df.copy()
    else:
        loan_source = gi_bill_df.copy()

    original_profession = row.get("Profession", "").strip()
    loan_source.columns = loan_source.columns.str.strip()
    profession = original_profession

    subset = loan_source.loc[loan_source["Profession"].str.strip() == profession]
    if subset.empty:
        print(f"[DEBUG] Profession '{profession}' not found.")
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

    try:
        months_school = int(loan_row.get("Months School", 0))
        monthly_in_school_savings = float(loan_row.get("Monthly Savings in School", 0.0))
        monthly_post_school_savings = float(loan_row.get("Monthly Savings", 0.0))
    except Exception as e:
        print(f"[DEBUG] Error reading financial parameters for '{profession}': {e}")
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

    if military_status.lower() != "no":
        try:
            monthly_post_school_savings = float(row.get("Monthly Savings", monthly_post_school_savings))
        except Exception as e:
            print(f"[DEBUG] Error reading post-school savings for '{profession}': {e}")
            monthly_post_school_savings = 0.0

    try:
        loan_values = loan_row[[f"month {i}" for i in range(1, total_months + 1)]].astype(float).values
    except Exception as e:
        print(f"[DEBUG] Error extracting loan values for '{profession}': {e}")
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

    accrued_savings = []
    for m in range(1, total_months + 1):
        if months_school > 0 and m <= months_school:
            if m == 1:
                current_savings = monthly_in_school_savings
            else:
                current_savings = accrued_savings[-1] + monthly_in_school_savings
            print(f"Month {m}: IN-SCHOOL. Added {monthly_in_school_savings}; Total: {current_savings}")
        else:
            if m == 1:
                current_savings = monthly_post_school_savings
            else:
                current_savings = accrued_savings[-1] * (1 + monthly_rate) + monthly_post_school_savings
            print(f"Month {m}: POST-SCHOOL. Added {monthly_post_school_savings}; Total: {current_savings}")
        accrued_savings.append(current_savings)

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

participant_df["Net Worth Over Time"] = participant_df.apply(
    lambda row: calculate_monthly_financials(row, skill_df, gi_bill_df),
    axis=1
)

for col in ['Months School', 'Monthly Savings in School', 'Monthly Savings']:
    if col in participant_df.columns:
        participant_df[col] = participant_df[col].fillna(0)

# -------------------------------------------------------------------------
# 5. Generate Individual Reports Incorporating Profession Data
# -------------------------------------------------------------------------
def generate_pair_report(c_row, m_row):
    """
    Generates an HTML report for a civilian (c_row) and military (m_row) participant pair.
    The report includes:
      - Financial details from the Skillset Cost Worksheet
      - Lifestyle decisions and costs from participant data
      - A job description for the Profession (civilian and military) from Profession Data
      - A chart comparing net worth at 20 years (month 240)
    """
    # Retrieve common financial details for the profession from skill_df
    profession = c_row.get("Profession", "").strip()
    skill_subset = skill_df[skill_df["Profession"].str.strip() == profession]
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

    # Look up job descriptions from Profession Data (assuming columns: Profession, Civilian Description, Military Description)
    prof_match = profession_df[profession_df["Profession"].str.strip().str.lower() == profession.lower()]
    if not prof_match.empty:
        prof_row = prof_match.iloc[0]
        civilian_desc = prof_row.get("Civilian Description", "Description not available.")
        military_desc = prof_row.get("Military Description", "Description not available.")
    else:
        civilian_desc = "Description not available."
        military_desc = "Description not available."

    # Retrieve lifestyle details
    c_lifestyle = {
        "Lifestyle Decisions": c_row.get("Lifestyle Decisions", "N/A"),
        "Lifestyle Cost": c_row.get("Lifestyle Cost", "N/A")
    }
    m_lifestyle = {
        "Lifestyle Decisions": m_row.get("Lifestyle Decisions", "N/A"),
        "Lifestyle Cost": m_row.get("Lifestyle Cost", "N/A")
    }

    # Extract net worth at 20 years (month 240) for both participants
    def get_networth_240(row):
        nw_list = row.get("Net Worth Over Time", [])
        if len(nw_list) >= 240:
            return nw_list[239]["Net Worth"]
        return None

    c_networth_240 = get_networth_240(c_row)
    m_networth_240 = get_networth_240(m_row)

    # Build a bar chart comparing net worth at 20 years
    chart_data = {"Name": [], "Net Worth": []}
    if c_networth_240 is not None:
        chart_data["Name"].append(c_row.get("Name", ""))
        chart_data["Net Worth"].append(c_networth_240)
    if m_networth_240 is not None:
        chart_data["Name"].append(m_row.get("Name", ""))
        chart_data["Net Worth"].append(m_networth_240)
    chart_df = pd.DataFrame(chart_data)
    chart_fig = px.bar(
        chart_df,
        x="Name",
        y="Net Worth",
        title="Net Worth Comparison at 20 Years",
        labels={"Net Worth": "Net Worth ($)", "Name": "Participant"}
    )
    chart_html = chart_fig.to_html(full_html=False, include_plotlyjs='cdn')

    # Build the HTML report
    report_html = f"""
    <html>
      <head>
        <title>Financial Report: {c_row.get("Name", "")} vs. {m_row.get("Name", "")}</title>
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
          .section {{
            margin-top: 20px;
          }}
          .lifestyle-tables {{
            display: flex;
            justify-content: space-between;
            margin-top: 20px;
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
            margin-top: 30px;
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
        <h1>Comparison Report: {c_row.get("Name", "")} vs. {m_row.get("Name", "")}</h1>
        <div class="section">
          <h3>Job Descriptions</h3>
          <p><strong>Civilian:</strong> {civilian_desc}</p>
          <p><strong>Military:</strong> {military_desc}</p>
        </div>
        <div class="section lifestyle-tables">
          <div>
            <h3>{c_row.get("Name", "")}'s Lifestyle</h3>
            <table>
              <tr><th>Lifestyle Decisions</th><th>Monthly Cost</th></tr>
              <tr>
                <td>{c_lifestyle.get("Lifestyle Decisions", "N/A")}</td>
                <td>{c_lifestyle.get("Lifestyle Cost", "N/A")}</td>
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
# 6. Generate Combined PDF Report
# -------------------------------------------------------------------------
def generate_combined_pdf_report(report_html_list, pdf_output_path):
    """
    Combines a list of HTML report strings into a single PDF file.
    Each report is separated by a page break.
    """
    combined_html = """
    <html>
      <head>
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

# -------------------------------------------------------------------------
# 7. Loop Through Participant Data to Generate Reports for Each Pair
# -------------------------------------------------------------------------
all_reports = []
for index, row in participant_df.iterrows():
    name = row.get("Name", "").strip()
    # Skip military entries (names ending with "-mil")
    if name.endswith("-mil"):
        continue
    mil_name = name + "-mil"
    mil_rows = participant_df[participant_df["Name"].str.strip() == mil_name]
    if mil_rows.empty:
        st.write(f"No military counterpart found for {name}. Skipping.")
        continue
    mil_row = mil_rows.iloc[0]
    report_html = generate_pair_report(row, mil_row)
    all_reports.append(report_html)
    # Optionally, save individual HTML files:
    individual_report_path = current_dir / f"report_{name}.html"
    with open(individual_report_path, "w", encoding="utf-8") as f:
        f.write(report_html)
    print(f"Generated report for {name} and {mil_name}: {individual_report_path}")

# -------------------------------------------------------------------------
# 8. Save the Combined PDF Report to the Output Folder
# -------------------------------------------------------------------------
output_folder = current_dir.parent / "data" / "output"
pdf_output_path = output_folder / "combined_reports.pdf"
generate_combined_pdf_report(all_reports, pdf_output_path)

st.write(f"Combined PDF report generated at: {pdf_output_path}")
