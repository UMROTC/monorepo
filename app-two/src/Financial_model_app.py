
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
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ])
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
# Get the current script's directory (app-two/src/)
current_dir = Path(__file__).parent.resolve()

# Define the monorepo root directory (two levels up from app-two/src/)
repo_root = current_dir.parent.parent

# Define paths to App Two's input CSVs
skillset_cost_worksheet_path = repo_root / 'app-one' / 'data' / 'input' / 'Skillset_cost_worksheet_CSV.csv'
# Load GI Bill Reduction data
gi_bill_path = repo_root / 'app-two' / 'data' / 'input' / 'GI_Bill_Application.csv'

try:
    gi_bill_df = pd.read_csv(gi_bill_path)
except FileNotFoundError as e:
    print(f"GI Bill reference sheet not found: {e}")
    exit()
except Exception as e:
    print(f"Error loading GI Bill reference sheet: {e}")
    exit()

# Define Paths to App Two's output CSVs
output_csv_path = current_dir.parent / "data" / "output" / "financial_model_plot.csv"
output_html_path = current_dir.parent / "data" / "output" / "plotly_bar_chart_race.html"

# -------------------------------------------------------------------------
# 3. Load & Merge
# -------------------------------------------------------------------------
# Load data from google sheet
client = authorize_gspread()
participant_df = get_google_sheet(client, SHEET_KEY, SHEET_NAME)

# Check if DataFrame is empty before processing
if participant_df.empty:
    st.warning("🚨 No participant data found! Please have participants fill out their surveys first.")
    st.stop()
    
# Load data from local files
try:
    skill_df = pd.read_csv(skillset_cost_worksheet_path)
except FileNotFoundError as e:
    print(f"File not found: {e}")
    exit()
except Exception as e:
    print(f"Error loading files: {e}")
    exit()

# Remove extra spaces in column names
participant_df.columns = participant_df.columns.str.strip()
skill_df.columns = skill_df.columns.str.strip()

# Merge on 'Career' (participant_df) vs 'Profession' (skill_df)
merged_data = participant_df.merge(skill_df, on="Profession", how="left") \
.merge(gi_bill_df, on="Profession", how="left")

# -------------------------------------------------------------------------
# 4. Calculate Monthly Net Worth
# -------------------------------------------------------------------------
def calculate_monthly_financials(row, skillset_df, gi_bill_df):
    """
    Calculates net worth by month over 25 years (300 months) for a participant.
    
    In-School Phase (months ≤ Years in School * 12):
      - Fixed monthly in-school savings = $104/month for all students in college.
      - Accrued savings = m * 104   [No compounding]

    Post-School Phase (months > Years in School * 12):
      - At m = (Years in School * 12) + 1, accrued savings = (total in-school savings) + (regular monthly savings)
      - For subsequent months, accrued savings compound at 5% annual (monthly rate) and add regular monthly savings.

    Loan Values:
      - The loan value is retrieved **per month** from the correct dataset (Skillset Cost for non-military, GI Bill for military).
      - The loan value used for each month is directly taken from its respective column (month 1, month 2, ..., month 300).

    Net Worth for each month is:
         Net Worth = Accrued Savings + Loan Value for that Month
         
    Returns:
      A list of dictionaries (one per month) with:
         "Month", "Accrued Savings", "Loan Value", "Net Worth"
    """
    total_months = 300
    monthly_rate = (1 + 0.05) ** (1/12) - 1  # Monthly rate for 5% annual compounding
    fixed_in_school_savings = 104  # Fixed $104 per month for college students

    # --- Determine School Duration ---
    yrs_in_school = float(row.get("Years in School", 0))
    school_months = int(yrs_in_school * 12)
    first_regular_month = school_months + 1

    # --- Post-School Savings Contribution ---
    monthly_savings_regular = float(row.get("Savings", 0.0))  # From participant data sheet

    # --- Loan Value (Now Uses Monthly Values Instead of Fixed Amount) ---
    who_pays = row.get("Who Pays for College", "").strip().lower()
    loan_source = gi_bill_df if who_pays in ["part time", "full time", "military"] else skillset_df
    loan_source.columns = loan_source.columns.str.lower().str.strip()

    profession = row.get("Profession", "").strip()
    if profession not in loan_source["profession"].values:
        raise KeyError(f"Profession '{profession}' not found in the loan dataset.")

    # Retrieve the loan row for this profession
    loan_row = loan_source.loc[loan_source["profession"] == profession].iloc[0]
    loan_values = loan_row[[f"month {i}" for i in range(1, total_months + 1)]].astype(float).values  # Get array of loan values

    # --- Calculate Accrued Savings ---
    accrued_savings = []
    for m in range(1, total_months + 1):
        if m <= school_months:
            # During school: accumulate savings linearly at a fixed $104/month
            current_savings = fixed_in_school_savings * m
        elif m == first_regular_month:
            # First month after school: total in-school savings + one month of regular savings
            current_savings = (fixed_in_school_savings * school_months) + monthly_savings_regular
        else:
            # Post-school: compound previous month's savings and add regular savings
            current_savings = accrued_savings[-1] * (1 + monthly_rate) + monthly_savings_regular
        accrued_savings.append(current_savings)

    # --- Compute Net Worth by Month Using the Correct Loan Values ---
    monthly_financials = []
    for m in range(1, total_months + 1):
        loan_value_for_month = loan_values[m - 1]  # Use the loan value for the current month
        net_worth = accrued_savings[m - 1] + loan_value_for_month
        monthly_financials.append({
            "Month": m,
            "Accrued Savings": accrued_savings[m - 1],
            "Loan Value": loan_value_for_month,
            "Net Worth": net_worth
        })

    return monthly_financials

# -------------------------------------------------------------------------
# 5. Fill Missing Columns
# -------------------------------------------------------------------------
for col in ['Years in School', 'Savings During School', 'Savings']:
    if col in merged_data.columns:
        merged_data[col] = merged_data[col].fillna(0)

for i in range(1, 181):
    c_name = f"month {i}"
    if c_name in merged_data.columns:
        merged_data[c_name] = merged_data[c_name].fillna(0)

# -------------------------------------------------------------------------
# 6. Add Net Worth Column
# -------------------------------------------------------------------------
merged_data["Net Worth Over Time"] = merged_data.apply(
    lambda row: calculate_monthly_financials(row, skill_df, gi_bill_df), axis=1
)
# -------------------------------------------------------------------------
# 7. Expand to Long Format
# -------------------------------------------------------------------------
expanded_rows = []
for _, row in merged_data.iterrows():  # Iterate over merged_data, not row directly
    for record in row["Net Worth Over Time"]:
        expanded_rows.append({
            "Name": row["Name"],
            "Profession": row["Profession"],
            "Month": record["Month"],
            "Savings Balance": record["Accrued Savings"],
            "Loan Balance": record["Loan Value"],
            "Net Worth": record["Net Worth"]
        })

# Convert list of dictionaries into a DataFrame
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
    color="Profession",  # Color by career/profession
    animation_frame="Month",
    text="Net Worth Label",
    title="Net Worth Over 25 Years - Yearly Slider & Pause Fix",
    labels={
        "Net Worth": "Net Worth ($)",
        "Name": "Participants",
        "Profession": "Career"
    },
    color_discrete_sequence=px.colors.qualitative.Set2  # Optional
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
for year in range(1, 26):  # 1..25 years
    final_month = year * 12
    slider_steps.append(dict(
        method="animate",
        label=f"Year {year}",
        args=[[
            f"{final_month}"],  # Target frame name
            {
                "mode": "immediate",
                "frame": {"duration": 500, "redraw": True},
                "transition": {"duration": 0},
            }
        ],
    ))

custom_slider = dict(
    active=0,
    steps=slider_steps,
    x=0.1,
    y=-0.3,  # Slider is now higher
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
    y=-0.4,  # Moved up
    buttons=[
        dict(
            label="Play",
            method="animate",
            args=[None, {"frame": {"duration": 300, "redraw": True}, "transition": {"duration": 0}, "fromcurrent": True}],
        ),
        dict(
            label="Pause",
            method="animate",
            args=[[None], {"mode": "immediate", "frame": {"duration": 0, "redraw": False}, "transition": {"duration": 0}}],
        ),
    ]
)

# -------------------------------------------------------------------------
# 13. Update Layout with Custom Slider & Buttons
# -------------------------------------------------------------------------
fig.update_layout(
    title=dict(
        text="Net Worth Over Time",
        x=0.5,  # Center title
        y=0.95,  # Position it slightly higher
        xanchor="center",
        yanchor="top",
        font=dict(size=24, color="black")
    ),    
    font=dict(color='black'),  # Set all text to black
    xaxis=dict(tickfont=dict(color='black')),  # Set x-axis text to black
    yaxis=dict(tickfont=dict(color='black')),  # Set y-axis text to black
    plot_bgcolor='white',  # Set background to white
    paper_bgcolor='white',  # Ensure full figure background is white
    sliders=[custom_slider],
    updatemenus=[play_pause_menu],
    margin=dict(l=50, r=50, t=50, b=200),  # Reduced bottom margin
    height=900,  # 50% more vertical space
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
