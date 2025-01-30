import streamlit as st
import pandas as pd
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials
import json
import requests
from io import StringIO

# ----------------------------------------------------------------------------
# 1. SET PAGE CONFIGURATION
# ----------------------------------------------------------------------------

# Must be the first Streamlit command
st.set_page_config(page_title="Budget Simulator", layout="wide")

# ----------------------------------------------------------------------------
# 2. DEFINE FUNCTIONS
# ----------------------------------------------------------------------------

def load_credentials():
    """
    Load Google service account credentials from Streamlit secrets.
    """
    try:
        # Retrieve credentials JSON string from Streamlit secrets
        if "gspread" not in st.secrets:
            st.error("❌ 'gspread' section missing in Streamlit secrets.")
            st.stop()
        
        if "service_account_key" not in st.secrets["gspread"]:
            st.error("❌ 'service_account_key' missing in Streamlit secrets['gspread'].")
            st.stop()

        service_account_json = st.secrets["gspread"]["service_account_key"]


        # If the JSON is stored as a string, parse it
        credentials_dict = json.loads(service_account_json) if isinstance(service_account_json, str) else service_account_json

        # Check if required keys exist
        required_keys = ["type", "project_id", "private_key", "client_email"]
        for key in required_keys:
            if key not in credentials_dict:
                st.error(f"❌ Missing key in credentials: {key}")
                st.stop()

        # Create credentials object
        creds = Credentials.from_service_account_info(credentials_dict, scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ])
        return creds

    except KeyError as e:
        st.error(f"❌ Missing key in secrets: {e}")
        st.stop()
    except json.JSONDecodeError as e:
        st.error(f"❌ Error decoding service account JSON: {e}")
        st.stop()
    except Exception as e:
        st.error(f"❌ Unexpected error loading credentials: {e}")
        st.stop()

        
def authorize_gspread():
    """
    Authorize gspread client with loaded credentials.
    """
    creds = load_credentials()
    try:
        scoped_creds = creds.with_scopes(['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
        client = gspread.authorize(scoped_creds)  # Convert creds properly
        return client
    except Exception as e:
        st.error(f"Error authorizing gspread client: {e}")
        st.stop()


def get_google_sheet(client, sheet_key, worksheet_name="participant_data"):
    """
    Access a specific worksheet in the Google Sheet.
    Args:
        client (gspread.Client): Authorized gspread client.
        sheet_key (str): Google Sheet ID.
        worksheet_name (str): Name of the worksheet to access.
    Returns:
        worksheet (gspread.Worksheet): Accessed worksheet.
    """
    try:
        sheet = client.open_by_key(sheet_key)
        worksheet = sheet.worksheet(worksheet_name)
        return worksheet
    except gspread.SpreadsheetNotFound:
        st.error("Google Sheet not found. Please check the SHEET_KEY in secrets.toml.")
        st.stop()
    except gspread.WorksheetNotFound:
        st.error(f"Worksheet '{worksheet_name}' not found in the Google Sheet.")
        st.stop()
    except Exception as e:
        st.error(f"Error accessing Google Sheet: {e}")
        st.stop()

def setup_paths():
    """
    Set up URLs for CSV input files from GitHub.
    Returns:
        urls (dict): Dictionary containing URLs to CSV files.
    """
    try:
        # GitHub repository details
        github_username = "UMROTC"
        github_repository = "monorepo"
        github_branch = "main"  # Ensure this is the correct branch name

        base_url = f"https://raw.githubusercontent.com/{github_username}/{github_repository}/{github_branch}/app-one/data/input"

        # Define raw GitHub URLs for CSV files
        tax_worksheet_url = f"{base_url}/2024_Tax_worksheet_CSV.csv"
        skillset_cost_url = f"{base_url}/Skillset_cost_worksheet_CSV.csv"
        lifestyle_decisions_url = f"{base_url}/Lifestyle_decisions_CSV.csv"

        urls = {
            "tax": tax_worksheet_url,
            "skillset": skillset_cost_url,
            "lifestyle": lifestyle_decisions_url
        }

        return urls
    except Exception as e:
        st.error(f"Error setting up URLs: {e}")
        st.stop()

@st.cache_data
def load_csv(url):
    """
    Load CSV data from the given GitHub raw URL.
    Args:
        url (str): URL to the CSV file.
    Returns:
        df (pd.DataFrame): Loaded DataFrame.
    """
    try:
        df = pd.read_csv(url)
        return df
    except pd.errors.ParserError as e:
        st.error(f"Error parsing CSV file from {url}: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Unexpected error loading CSV file from {url}: {e}")
        st.stop()

def calculate_tax(income, tax_brackets):
    """
    Compute progressive tax based on brackets.
    Args:
        income (float): Taxable income.
        tax_brackets (pd.DataFrame): DataFrame containing tax brackets.
    Returns:
        tax (float): Total tax calculated.
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
    Calculate total federal + state tax for a given marital status.
    Args:
        income (float): Annual income.
        marital_status (str): 'Single' or 'Married'.
        tax_data (pd.DataFrame): DataFrame containing tax information.
    Returns:
        taxable_income (float): Taxable income after deductions.
        federal_tax (float): Federal tax owed.
        state_tax (float): State tax owed.
        total_tax (float): Total tax owed.
    """
    federal_brackets = tax_data[
        (tax_data["Status"] == marital_status) & (tax_data["Type"] == "Federal")
    ]
    state_brackets = tax_data[
        (tax_data["Status"] == marital_status) & (tax_data["Type"] == "State")
    ]

    if federal_brackets.empty or state_brackets.empty:
        st.error("Tax data is missing or invalid. Please check your CSV.")
        return 0, 0, 0, 0

    standard_deduction = federal_brackets.iloc[0]["Standard Deduction"]
    taxable_income = max(0, float(income) - float(standard_deduction))

    federal_tax = calculate_tax(taxable_income, federal_brackets)
    state_tax = calculate_tax(taxable_income, state_brackets)
    total_tax = federal_tax + state_tax
    return taxable_income, federal_tax, state_tax, total_tax

def save_participant_data(data_frame, worksheet):
    """
    Appends each row of data_frame to the 'participant_data' worksheet in your Google Sheet.
    Args:
        data_frame (pd.DataFrame): DataFrame containing participant data.
        worksheet (gspread.Worksheet): The target worksheet.
    """
    try:
        # Convert DataFrame to list of lists
        rows_to_add = data_frame.values.tolist()
        for row in rows_to_add:
            worksheet.append_row(row, value_input_option="RAW")
        st.success("Your budget has been submitted and saved to Google Sheets successfully!")
    except Exception as e:
        st.error(f"Failed to save participant data to Google Sheets: {e}")

# ----------------------------------------------------------------------------
# 3. MAIN APP LOGIC
# ----------------------------------------------------------------------------

def main():
    st.title("Budget Simulator")

    urls = setup_paths()
    tax_data = load_csv(urls["tax"])
    skillset_data = load_csv(urls["skillset"])
    lifestyle_data = load_csv(urls["lifestyle"])

    # Step 1: Participant Name
    st.header("Step 1: Enter Your Name")
    participant_name = st.text_input("Name")

    # Step 2: Career Choice
    st.header("Step 2: Choose Your Career")
    career = st.selectbox("Select a Career", skillset_data["Profession"])
    selected_career = skillset_data[skillset_data["Profession"] == career].iloc[0]
    if selected_career["Requires School"].lower() == "yes":
        salary = selected_career["Savings During School"]
    else:
        salary = selected_career["Average Salary"]

    # Step 3: Marital Status
    st.header("Step 3: Choose Your Marital Status")
    marital_status = st.radio("Marital Status", ["Single", "Married"])

    taxable_income, federal_tax, state_tax, total_tax = calculate_tax_by_status(
        salary, marital_status, tax_data
    )

    standard_deduction = tax_data[
        (tax_data["Status"] == marital_status) & (tax_data["Type"] == "Federal")
    ].iloc[0]["Standard Deduction"]

    st.write(f"**Annual Salary:** ${salary:,.2f}")
    st.write(f"**Standard Deduction:** ${standard_deduction:,.2f}")
    st.write(f"**Taxable Income:** ${taxable_income:,.2f}")
    st.write(f"**Federal Tax:** ${federal_tax:,.2f}")
    st.write(f"**State Tax:** ${state_tax:,.2f}")
    st.write(f"**Total Tax:** ${total_tax:,.2f}")

    monthly_income_after_tax = (salary - federal_tax - state_tax) / 12
    st.write(f"**Monthly Income After Tax:** ${monthly_income_after_tax:,.2f}")

    # Sidebar for remaining budget
    st.sidebar.header("Remaining Monthly Budget")
    remaining_budget_display = st.sidebar.empty()
    remaining_budget_message = st.sidebar.empty()

    # Initialize variables
    remaining_budget = monthly_income_after_tax
    expenses = 0
    savings = 0
    selected_lifestyle_choices = {}

    # Step 4: Military Service
    st.header("Step 4: Military Service")
    military_service_choice = st.selectbox(
        "Choose your military service option", ["No", "Part Time", "Full Time"], key="Military_Service"
    )
    selected_lifestyle_choices["Military Service"] = {"Choice": military_service_choice, "Cost": 0}

    # Define restrictions based on military service
    restricted_options = {
     "No": ["Military"],  # Completely restrict "Military" from all lifestyle choices
    "Part Time": ["Housing", "Food"],  # "Military" is not allowed for these, but allowed for Children, College, and Health Insurance
    "Full Time": []  # No restrictions, "Military" is allowed everywhere
}

    # Step 5: Lifestyle Choices (Except Savings)
    st.header("Step 5: Make Lifestyle Choices")
    lifestyle_categories = list(lifestyle_data["Category"].unique())

    for idx, category in enumerate(lifestyle_categories):
        if category == "Savings":
            continue  # We'll handle Savings separately

        st.subheader(category)
        options = lifestyle_data[lifestyle_data["Category"] == category]["Option"].tolist()

        # Restrict "Military" if needed
        if "Military" in options and military_service_choice in restricted_options:
            if category in restricted_options[military_service_choice]:
                options.remove("Military")

        choice = st.selectbox(f"Choose your {category.lower()}", options, key=f"{category}_choice_{idx}")
    st.markdown("""
        <style>
        div[data-testid="stSelectbox"] > label + div > div {
        background-color: white !important;
        }
        div[data-testid="stSelectbox"] select:focus {
        background-color: white !important;
        }
        div[data-testid="stSelectbox"] select:after {
        background-color: #f0f0f0 !important;
        }
        </style>
        """, unsafe_allow_html=True)

        # Get the corresponding cost
    try:
            cost = lifestyle_data[
                (lifestyle_data["Category"] == category) & (lifestyle_data["Option"] == choice)
            ]["Monthly Cost"].values[0]
    except IndexError:
            st.error(f"Cost information missing for {choice} in {category}.")
            cost = 0

    if remaining_budget - cost < 0:
            st.error(
                f"Warning: Choosing {choice} for {category} exceeds your budget by "
                f"${abs(remaining_budget - cost):,.2f}!"
            )
            remaining_budget -= cost
    else:
            remaining_budget -= cost

    expenses += cost
    selected_lifestyle_choices[category] = {"Choice": choice, "Cost": cost}

    # Step 5b: Savings
    st.subheader("Savings")
    savings_options = lifestyle_data[lifestyle_data["Category"] == "Savings"]["Option"].tolist()
    savings_choice = st.selectbox("Choose your savings option", savings_options, key="Savings_Choice")

    if savings_choice.lower() == "whatever is left":
        savings = remaining_budget
        remaining_budget = 0
    else:
        # Assuming the 'Percentage' column exists and is a string like '10%'
        try:
            savings_percentage = lifestyle_data[
                (lifestyle_data["Category"] == "Savings") & (lifestyle_data["Option"] == savings_choice)
            ]["Percentage"].values[0]
            if pd.notna(savings_percentage) and isinstance(savings_percentage, str) and "%" in savings_percentage:
                savings_percentage = float(savings_percentage.strip("%")) / 100
                savings = savings_percentage * monthly_income_after_tax
            else:
                savings = 0
        except IndexError:
            st.error(f"Savings percentage not found for choice: {savings_choice}")
            savings = 0

        if savings > remaining_budget:
            st.error(
                f"Warning: Your savings choice exceeds your budget by "
                f"${abs(remaining_budget - savings):,.2f}!"
            )
            remaining_budget -= savings
        else:
            remaining_budget -= savings

    selected_lifestyle_choices["Savings"] = {"Choice": savings_choice, "Cost": savings}

    # Update sidebar
    remaining_budget_display.markdown(f"### Remaining Monthly Budget: ${remaining_budget:,.2f}")
    if remaining_budget > 0:
        remaining_budget_message.success(f"You have ${remaining_budget:,.2f} left.")
    elif remaining_budget == 0:
        remaining_budget_message.success("You have balanced your budget!")
    else:
        remaining_budget_message.error(f"You have overspent by ${-remaining_budget:,.2f}!")

    # Display a summary of all choices
    st.subheader("Lifestyle Choices Summary")
    for cat, details in selected_lifestyle_choices.items():
        st.write(f"**{cat}:** {details['Choice']} - ${details['Cost']:,.2f}")

    # Step 6: Submit
    st.header("Step 6: Submit Your Budget")
    st.write(f"**Remaining Budget:** ${remaining_budget:,.2f}")

    gspread_client = authorize_gspread()
    SHEET_KEY = "1rgS_NxsZjDkPE07kEpuYxvwktyROXKUfYBk-4t9bkqA"


    if participant_name and career and remaining_budget == 0:
        submit = st.button("Submit")
        if submit:
            # Build the DataFrame with all relevant fields
            data = pd.DataFrame({
                "Name": [participant_name],
                "Profession": [career],
                "Military Service": [selected_lifestyle_choices.get("Military Service", {}).get("Choice", "No")],
                "Savings": [savings],
                "Marital Status": [marital_status],
                "Taxable Income": [taxable_income],
                "Federal Tax": [federal_tax],
                "State Tax": [state_tax],
                "Total Tax": [total_tax],
                "Monthly Income After Tax": [monthly_income_after_tax],
                # Add other relevant fields as needed
            })

            # Access the Google Sheet
            worksheet = get_google_sheet(gspread_client, SHEET_KEY, "participant_data")
            save_participant_data(data, worksheet)
    else:
        st.info("Please complete all steps and ensure your budget is balanced before submitting.")

# ----------------------------------------------------------------------------
# 4. EXECUTE MAIN FUNCTION
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
