import streamlit as st
import pandas as pd
import requests
import gspread
import json
from pathlib import Path
from google.oauth2.service_account import Credentials

# ----------------------------------------------------------------------------
# 1. GOOGLE SHEETS AUTHENTICATION USING GSPREAD
# ----------------------------------------------------------------------------

def load_credentials():
    """
    Load Google service account credentials from Streamlit secrets.
    """
    try:
        service_account_json = st.secrets["gspread"]["service_account_key"]

        if isinstance(service_account_json, str):
            credentials_dict = json.loads(service_account_json)
        elif isinstance(service_account_json, dict):
            credentials_dict = service_account_json
        else:
            raise ValueError("Invalid format for service_account_key in secrets.")

        creds = Credentials.from_service_account_info(credentials_dict, scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ])
        return creds
    except Exception as e:
        st.error(f"Error loading Google credentials: {e}")
        st.stop()

def authorize_gspread(creds):
    """
    Authorize gspread client.
    """
    try:
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Error authorizing gspread client: {e}")
        st.stop()

def get_google_sheet(client, sheet_key, worksheet_name="participant_data"):
    """
    Get Google Sheets worksheet.
    """
    try:
        sheet = client.open_by_key(sheet_key)
        worksheet = sheet.worksheet(worksheet_name)
        return worksheet
    except Exception as e:
        st.error(f"Error accessing Google Sheet: {e}")
        st.stop()

# Load credentials
creds = load_credentials()
gspread_client = authorize_gspread(creds)

# ----------------------------------------------------------------------------
# 2. DOWNLOAD CSV FILES FROM GITHUB
# ----------------------------------------------------------------------------

GITHUB_BASE_URL = "https://raw.githubusercontent.com/UMROTC/monorepo/main/app-one/data/input/"

CSV_FILES = {
    "tax": "2024_Tax_worksheet_CSV.csv",
    "skillset": "Skillset_cost_worksheet_CSV.csv",
    "lifestyle": "Lifestyle_decisions_CSV.csv",
}

def download_csv(file_name):
    """
    Download CSV file from GitHub.
    """
    file_url = GITHUB_BASE_URL + file_name
    response = requests.get(file_url)
    
    if response.status_code == 200:
        return pd.read_csv(pd.compat.StringIO(response.text))
    else:
        st.error(f"Failed to download {file_name}. Please check the GitHub path.")
        st.stop()

# Load data
tax_data = download_csv(CSV_FILES["tax"])
skillset_data = download_csv(CSV_FILES["skillset"])
lifestyle_data = download_csv(CSV_FILES["lifestyle"])

# Convert numeric columns
numeric_columns_skillset = ["Savings During School", "Average Salary"]
for col in numeric_columns_skillset:
    if col in skillset_data.columns:
        skillset_data[col] = pd.to_numeric(skillset_data[col], errors="coerce").fillna(0)

# ----------------------------------------------------------------------------
# 3. TAX FUNCTIONS
# ----------------------------------------------------------------------------

def calculate_tax(income, tax_brackets):
    """
    Compute progressive tax based on brackets.
    """
    tax = 0
    for _, row in tax_brackets.iterrows():
        lower = row["Lower Bound"]
        upper = row["Upper Bound"] if not pd.isna(row["Upper Bound"]) else float("inf")
        rate = row["Rate"]
        if income > lower:
            taxable = min(income, upper) - lower
            tax += taxable * rate
        else:
            break
    return tax

def calculate_tax_by_status(income, marital_status, tax_data):
    """
    Calculate federal and state tax based on marital status.
    """
    federal_brackets = tax_data[(tax_data["Status"] == marital_status) & (tax_data["Type"] == "Federal")]
    state_brackets = tax_data[(tax_data["Status"] == marital_status) & (tax_data["Type"] == "State")]

    if federal_brackets.empty or state_brackets.empty:
        st.error("Tax data is missing or invalid. Please check your CSV.")
        return 0, 0, 0, 0

    standard_deduction = federal_brackets.iloc[0]["Standard Deduction"]
    taxable_income = max(0, float(income) - float(standard_deduction))

    federal_tax = calculate_tax(taxable_income, federal_brackets)
    state_tax = calculate_tax(taxable_income, state_brackets)
    total_tax = federal_tax + state_tax
    return taxable_income, federal_tax, state_tax, total_tax

# ----------------------------------------------------------------------------
# 4. SAVE DATA TO GOOGLE SHEETS
# ----------------------------------------------------------------------------

def save_participant_data(data_frame, sheet_key):
    """
    Save participant data to Google Sheets.
    """
    try:
        worksheet = get_google_sheet(gspread_client, sheet_key, "participant_data")
        worksheet.append_rows(data_frame.values.tolist(), value_input_option="RAW")
        st.success("Your budget has been submitted and saved to Google Sheets successfully!")
    except Exception as e:
        st.error(f"Failed to save data to Google Sheets: {e}")

# ----------------------------------------------------------------------------
# 5. STREAMLIT APP LOGIC
# ----------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Budget Simulator", layout="wide")
    st.title("Budget Simulator")

    # Step 1: Name
    st.header("Step 1: Enter Your Name")
    participant_name = st.text_input("Name")

    # Step 2: Career
    st.header("Step 2: Choose Your Career")
    career = st.selectbox("Select a Career", skillset_data["Profession"])
    selected_career = skillset_data[skillset_data["Profession"] == career].iloc[0]
    salary = selected_career["Average Salary"] if selected_career["Requires School"].lower() != "yes" else selected_career["Savings During School"]

    # Step 3: Marital Status
    st.header("Step 3: Choose Your Marital Status")
    marital_status = st.radio("Marital Status", ["Single", "Married"])

    taxable_income, federal_tax, state_tax, total_tax = calculate_tax_by_status(salary, marital_status, tax_data)
    monthly_income_after_tax = (salary - federal_tax - state_tax) / 12

    st.write(f"**Annual Salary:** ${salary:,.2f}")
    st.write(f"**Total Tax:** ${total_tax:,.2f}")
    st.write(f"**Monthly Income After Tax:** ${monthly_income_after_tax:,.2f}")

    # Step 4: Military Service
    st.header("Step 4: Military Service")
    military_service_choice = st.selectbox("Choose military service option", ["No", "Part Time", "Full Time"])

    # Step 5: Lifestyle Choices
    st.header("Step 5: Lifestyle Choices")
    lifestyle_choices = {}
    remaining_budget = monthly_income_after_tax

    for category in lifestyle_data["Category"].unique():
        if category == "Savings":
            continue
        
        options = lifestyle_data[lifestyle_data["Category"] == category]["Option"].tolist()
        choice = st.selectbox(f"{category} Choice", options)
        cost = lifestyle_data[(lifestyle_data["Category"] == category) & (lifestyle_data["Option"] == choice)]["Monthly Cost"].values[0]

        remaining_budget -= cost
        lifestyle_choices[category] = {"Choice": choice, "Cost": cost}

    # Step 6: Submit
    st.header("Step 6: Submit Your Budget")
    
    SHEET_KEY = st.secrets["SHEET_KEY"]

    if participant_name and career and remaining_budget >= 0:
        submit = st.button("Submit")
        if submit:
            data = pd.DataFrame([[participant_name, career, military_service_choice, marital_status, taxable_income, federal_tax, state_tax, total_tax, monthly_income_after_tax]])
            save_participant_data(data, SHEET_KEY)
    else:
        st.info("Complete all steps and ensure budget is balanced before submitting.")

if __name__ == "__main__":
    main()
