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
skill_df.columns = skill_df.columns.str.strip()
# (gi_bill_df remains as loaded; ensure its headers are also properly stripped if necessary)
gi_bill_df.columns = gi_bill_df.columns.str.strip()

print("Participant data columns:", participant_df.columns.tolist())
print("Skillset cost worksheet columns:", skill_df.columns.tolist())
print("GI Bill data columns:", gi_bill_df.columns.tolist())

# Optional debug loop to check each participant's profession in the appropriate financial data:
for i, row in participant_df.iterrows():
    ms = str(row.get("Military Service", "")).strip()
    if ms.lower() == "no":
        loan_source = skill_df
    else:
        loan_source = gi_bill_df
    # Do not change case; just strip whitespace
    prof = str(row.get("profession", "")).strip()
    matching = loan_source.loc[loan_source["profession"].str.strip() == prof]
    if matching.empty:
        print(f"[DEBUG] Row={i}, Name='{row.get('Name')}', profession='{row.get('profession')}'"
              f" => NOT FOUND in {'skill_df' if ms.lower()=='no' else 'gi_bill_df'}")

# -------------------------------------------------------------------------
# 4. Calculate Monthly Net Worth
# -------------------------------------------------------------------------
def calculate_monthly_financials(row, skill_df, gi_bill_df):
    total_months = 300
    monthly_rate = (1 + 0.05) ** (1/12) - 1  # ~0.00407 for 5% APR

    # 1) Pull participant's data
    months_school = int(row.get("Months School", 0))
    monthly_in_school_savings = float(row.get("Monthly Savings in School", 0.0))
    monthly_post_school_savings = float(row.get("Monthly Savings", 0.0))

    # 2) Decide which loan data to use based on Military Service
    military_status = str(row.get("Military Service", "")).strip()
    if military_status.lower() == "no":
        loan_source = skill_df.copy()
    else:
        loan_source = gi_bill_df.copy()

    # 3) Save the original profession (for display) and standardize for lookup
    original_profession = row.get("profession", "").strip()
    # Standardize loan_source columns by stripping whitespace (do not change case)
    loan_source.columns = loan_source.columns.str.strip()
    # Create a standardized version for matching (without changing capitalization)
    profession = original_profession

    # 4) Filter the loan_source by the standardized profession
    subset = loan_source.loc[loan_source["profession"].str.strip() == profession]
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

    # 5) Extract monthly loan values
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

    # 6) Compute monthly accrued savings
    accrued_savings = []
    for m in range(1, total_months + 1):
        if m == 1:
            current_savings = monthly_in_school_savings if months_school >= 1 else monthly_post_school_savings
        else:
            prev_savings = accrued_savings[-1]
            if m <= months_school:
                current_savings = prev_savings + monthly_in_school_savings
            elif m == (months_school + 1):
                current_savings = prev_savings * (1 + monthly_rate) + monthly_post_school_savings
            else:
                current_savings = prev_savings * (1 + monthly_rate) + monthly_post_school_savings
        accrued_savings.append(current_savings)

    # 7) Compute monthly net worth and include the properly capitalized profession for output
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

# Apply the calculation function to participant data (no merging with financial data)
participant_df["Net Worth Over Time"] = participant_df.apply(
    lambda row: calculate_monthly_financials(row, skill_df, gi_bill_df),
    axis=1
)

# -------------------------------------------------------------------------
# 5. Fill Missing Columns in participant_df (if needed)
# -------------------------------------------------------------------------
for col in ['Months School', 'Monthly Savings in School', 'Monthly Savings']:
    if col in participant_df.columns:
        participant_df[col] = participant_df[col].fillna(0)

# -------------------------------------------------------------------------
# 7. Expand to Long Format
# -------------------------------------------------------------------------
expanded_rows = []
for _, row in participant_df.iterrows():
    for record in row["Net Worth Over Time"]:
        expanded_rows.append({
            "Name": row["Name"],
            "profession": row["profession"],  # Use the participant's value (capitalized)
            "Month": record["Month"],
            "Savings Balance": record["Accrued Savings"],
            "Loan Balance": record["Loan Value"],
            "Net Worth": record["Net Worth"],
            "ProfessionDisplay": record["Profession"]  # For display purposes
        })

expanded_df = pd.DataFrame(expanded_rows)

# -------------------------------------------------------------------------
# 8. Accounting-Style Label
# -------------------------------------------------------------------------
expanded_df['Net Worth Label'] = expanded_df['Net Worth'].apply(
    lambda x: f"(${abs(x):,.2f})" if x < 0 else f"${x:,.2f}"
)

# -------------------------------------------------------------------------
# 9. Save to CSV
# -------------------------------------------------------------------------
try:
    expanded_df.to_csv(output_csv_path, index=False)
    print(f"Monthly data saved to CSV at: {output_csv_path}")
except Exception as e:
    print("Error saving CSV:", e)

# -------------------------------------------------------------------------
# 10. Create Bar Chart Figure
# -------------------------------------------------------------------------
fig = px.bar(
    expanded_df,
    x="Net Worth",
    y="Name",
    orientation="h",
    color="profession",  # Color by career/profession
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
# 11. Define Slider Steps (Yearly)
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
# 13. Update Layout with Custom Slider & Buttons
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
# 14. Save & Show
# -------------------------------------------------------------------------
try:
    fig.write_html(output_html_path)
    print(f"Bar chart saved to HTML at: {output_html_path}")
except Exception as e:
    print("Error saving HTML file:", e)

st.plotly_chart(fig)

print("Script complete.")
