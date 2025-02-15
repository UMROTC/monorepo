
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
def calculate_net_worth_table(participant_df, skillset_df, gi_bill_df):
    """
    Calculates the net worth by month for each participant over 25 years (300 months).
    
    Steps:
      1. Calculate accrued savings by month for each participant.
         - Savings compound monthly at a 5% annual rate.
      2. Reference the participant's student loan values by month from the correct dataset:
         - If Who Pays for College is "Military", use gi_bill_df.
         - Otherwise, use skillset_df.
         - Matching is done based on the participant's Profession.
      3. For each month, add the accrued savings to the given loan value.
         (No loan payment calculations are done; the loan values remain fixed as provided.)
      4. Return a DataFrame with columns: Name, Profession, and month 1, month 2, …, month 300.
    """
    import pandas as pd

    total_months = 300
    # Monthly savings growth rate from a 5% annual return compounded monthly
    monthly_interest_rate = (1 + 0.05) ** (1/12) - 1

    # Build a table of accrued savings by month for each participant.
    # We'll assume that savings start immediately.
    accrued_savings = {}
    for idx, row in participant_df.iterrows():
        name = row["Name"]
        monthly_savings = float(row.get("Savings", 0.0))
        savings_by_month = []
        current_savings = 0.0
        for month in range(1, total_months + 1):
            if month == 1:
                current_savings = monthly_savings
            else:
                current_savings = current_savings * (1 + monthly_interest_rate) + monthly_savings
            savings_by_month.append(current_savings)
        accrued_savings[name] = savings_by_month
    # Create a DataFrame from accrued savings (rows=participant Name, columns="month 1", "month 2", ..., "month 300")
    savings_df = pd.DataFrame(accrued_savings, 
                              index=[f"month {i}" for i in range(1, total_months + 1)]).T

    # For each participant, look up the corresponding monthly loan values.
    # Use "Who Pays for College" to decide which reference to use,
    # and match by "Profession".
    net_worth_df = savings_df.copy()  # We'll add the loan values to these savings.
    for idx, row in participant_df.iterrows():
        name = row["Name"]
        profession = row.get("Profession", "").strip()
        who_pays = row.get("Who Pays for College", "").strip().lower()
        # Choose the correct loan dataset.
        loan_source = gi_bill_df if who_pays == "military" else skillset_df
        # Standardize column names in the loan source
        loan_source.columns = loan_source.columns.str.lower().str.strip()
        # Assume the loan source has a column "profession" that we match against.
        participant_loan = loan_source[loan_source["profession"] == profession]
        if not participant_loan.empty:
            # Extract the monthly loan values for months 1..total_months.
            # (Assume columns are named exactly "month 1", "month 2", etc.)
            loan_values = participant_loan.iloc[0][[f"month {i}" for i in range(1, total_months + 1)]]
            # Convert to float (if not already)
            loan_values = loan_values.astype(float)
        else:
            # If no matching loan row is found, assume zero loan.
            loan_values = pd.Series([0.0] * total_months, index=[f"month {i}" for i in range(1, total_months + 1)])
        # Now, net worth = accrued savings + loan value (per month)
        # (We add elementwise; note: loan values are assumed to be provided and remain fixed.)
        net_worth_df.loc[name] = net_worth_df.loc[name].astype(float) + loan_values.values

    # Create the final table that includes Name and Profession.
    final_df = net_worth_df.copy()
    final_df.reset_index(inplace=True)
    final_df.rename(columns={"index": "Name"}, inplace=True)
    # Merge with participant_df to get the Profession column.
    final_df = final_df.merge(participant_df[["Name", "Profession"]], on="Name", how="left")
    # Rearrange columns so that Name and Profession come first.
    month_cols = [col for col in final_df.columns if col.startswith("month")]
    final_df = final_df[["Name", "Profession"] + month_cols]
    
    return final_df

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
            "Savings Balance": record["Savings Balance"],
            "Loan Balance": record["Loan Balance"],
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
