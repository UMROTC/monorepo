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

st.set_page_config(page_title="Budget Simulator", layout="wide")

# ----------------------------------------------------------------------------
# 2. DEFINE FUNCTIONS
# ----------------------------------------------------------------------------

def load_credentials():
    """
    Load Google service account credentials from Streamlit secrets.
    """
    try:
        if "gspread" not in st.secrets:
            st.error("❌ 'gspread' section missing in Streamlit secrets.")
            st.stop()
        
        if "service_account_key" not in st.secrets["gspread"]:
            st.error("❌ 'service_account_key' missing in Streamlit secrets['gspread'].")
            st.stop()

        service_account_json = st.secrets["gspread"]["service_account_key"]
        credentials_dict = (
            json.loads(service_account_json)
            if isinstance(service_account_json, str)
            else service_account_json
        )

        required_keys = ["type", "project_id", "private_key", "client_email"]
        for key in required_keys:
            if key not in credentials_dict:
                st.error(f"❌ Missing key in credentials: {key}")
                st.stop()

        creds = Credentials.from_service_account_info(
            credentials_dict,
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
        )
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
        scoped_creds = creds.with_scopes([
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ])
        client = gspread.authorize(scoped_creds)
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
    """
    try:
        github_username = "UMROTC"
        github_repository = "monorepo"
        github_branch = "main"

        base_url = f"https://raw.githubusercontent.com/{github_username}/{github_repository}/{github_branch}/app-one/data/input"

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
    """
    try:
        df = pd.read_csv(url)
        # Clean out potential BOM or whitespace
        df.columns = df.columns.str.strip().str.replace('\ufeff', '')
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
    """
    # Sort brackets to be safe
    tax_brackets = tax_brackets.sort_values(by="Lower Bound")
    
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
    Appends each row of data_frame to the 'participant_data' worksheet.
    """
    try:
        rows_to_add = data_frame.values.tolist()
        # Since we're only appending a single row at a time, pick row 0
        worksheet.append_row(rows_to_add[0], value_input_option="RAW")
        st.success("Your budget has been submitted and saved to Google Sheets successfully!")
    except Exception as e:
        st.error(f"Failed to save participant data to Google Sheets: {e}")


# ----------------------------------------------------------------------------
# 3. MAIN APP LOGIC
# ----------------------------------------------------------------------------
def main():
    st.title("Budget Simulator")
        
    # Load and cache data
    urls = setup_paths()
    tax_data = load_csv(urls["tax"])
    skillset_data = load_csv(urls["skillset"])
    lifestyle_data = load_csv(urls["lifestyle"])

    # If "profession" exists, rename to "Profession"
    if "profession" in skillset_data.columns:
        skillset_data.rename(columns={"profession": "Profession"}, inplace=True)

    # Step 1: Participant Name
    st.header("Step 1: Enter Your Name")
    participant_name = st.text_input("Name")

    # Step 2: Profession Choice
    st.header("Step 2: Choose Your Profession")
    Profession = st.selectbox("Select a Profession", skillset_data["Profession"])
    selected_Profession = skillset_data[skillset_data["Profession"] == Profession].iloc[0]

    # Salary logic: if Requires School == "yes", use "Savings During School", else "Average Salary"
    if selected_Profession["Requires School"].lower() == "yes":
        salary = selected_Profession["Savings During School"]
    else:
        salary = selected_Profession["Average Salary"]

    # Step 3: Marital Status
    st.header("Step 3: Choose Your Marital Status")
    marital_status = st.radio("Marital Status", ["Single", "Married"])

    # Calculate taxes
    taxable_income, federal_tax, state_tax, total_tax = calculate_tax_by_status(
        salary, marital_status, tax_data
    )
    standard_deduction = tax_data[
        (tax_data["Status"] == marital_status) & (tax_data["Type"] == "Federal")
    ].iloc[0]["Standard Deduction"]

    # Display
    st.write(f"**Annual Salary:** ${salary:,.2f}")
    st.write(f"**Standard Deduction:** ${standard_deduction:,.2f}")
    st.write(f"**Taxable Income:** ${taxable_income:,.2f}")
    st.write(f"**Federal Tax:** ${federal_tax:,.2f}")
    st.write(f"**State Tax:** ${state_tax:,.2f}")
    st.write(f"**Total Tax:** ${total_tax:,.2f}")

    monthly_income_after_tax = (salary - federal_tax - state_tax) / 12
    st.write(f"**Monthly Income After Tax:** ${monthly_income_after_tax:,.2f}")

    # Sidebar budget display
    st.sidebar.header("Remaining Monthly Budget")
    remaining_budget_display = st.sidebar.empty()
    remaining_budget_message = st.sidebar.empty()

    # Track budget
    remaining_budget = monthly_income_after_tax
    expenses = 0
    savings = 0
    selected_lifestyle_choices = {}

    # Step 4: Military Service
    st.header("Step 4: Military Service")
    military_service_choice = st.selectbox(
        "Choose your military service option",
        ["No", "Part Time", "Full Time"],
        key="Military_Service"
    )
    # Store text only (cost=0 placeholder)
    selected_lifestyle_choices["Military Service"] = {"Choice": military_service_choice, "Cost": 0}

    # Define which categories can have "Military" as an option
    allowed_military_part_time = ["Children", "Who Pays for College", "Health Insurance"]
    allowed_military_full_time = ["Housing", "Food", "Children", "Who Pays for College", "Health Insurance"]

    # Step 5: Lifestyle Choices
    st.header("Step 5: Make Lifestyle Choices")

    for category in lifestyle_data["Category"].unique():
        # We'll skip "Savings" until after this loop
        if category == "Savings":
            continue

        # Grab all possible options for this category
        options = lifestyle_data[lifestyle_data["Category"] == category]["Option"].tolist()

        # If "Military" is in the options, remove it unless it's valid for the chosen service
        if "Military" in options:
            if military_service_choice == "No":
                options.remove("Military")
            elif military_service_choice == "Part Time" and category not in allowed_military_part_time:
                options.remove("Military")
            elif military_service_choice == "Full Time" and category not in allowed_military_full_time:
                options.remove("Military")

        if not options:
            st.warning(f"No available options for '{category}' given your current military choice.")
            continue

        choice = st.selectbox(f"Choose your {category.lower()}", options, key=f"{category}_choice")
        cost_row = lifestyle_data[
            (lifestyle_data["Category"] == category) & (lifestyle_data["Option"] == choice)
        ]

        cost = 0
        if not cost_row.empty and "Monthly Cost" in cost_row:
            try:
                cost = float(cost_row["Monthly Cost"].values[0])
            except ValueError:
                cost = 0

        remaining_budget -= cost
        expenses += cost
        selected_lifestyle_choices[category] = {"Choice": choice, "Cost": cost}

    # Step 5b: Savings
    st.subheader("Savings")
    savings_options = lifestyle_data[lifestyle_data["Category"] == "Savings"]["Option"].tolist()
    savings_choice = st.selectbox("Choose your savings option", savings_options, key="Savings_Choice")

    if savings_choice.lower() == "whatever is left":
        # If user has already overspent or is at 0, cannot save
        if remaining_budget <= 0:
            st.warning("You have no remaining budget to save—your total expenses exceed your income.")
            savings = 0
        else:
            # Save exactly what's left
            savings = remaining_budget
        # Let the budget go negative if it was already negative (no clamping)
        remaining_budget -= savings
    else:
        try:
            savings_row = lifestyle_data[
                (lifestyle_data["Category"] == "Savings") & 
                (lifestyle_data["Option"] == savings_choice)
            ]
            savings_percentage_str = savings_row["Percentage"].values[0]  # e.g. "10%"
            if (
                pd.notna(savings_percentage_str)
                and isinstance(savings_percentage_str, str)
                and "%" in savings_percentage_str
            ):
                savings_percentage = float(savings_percentage_str.strip("%")) / 100
                savings = savings_percentage * monthly_income_after_tax
            else:
                savings = 0
        except Exception:
            st.error(f"Savings percentage not found or invalid for choice: {savings_choice}")
            savings = 0

        if savings > remaining_budget:
            st.error(
                f"Warning: Your savings choice exceeds your budget by "
                f"${abs(remaining_budget - savings):,.2f}!"
            )
            savings = remaining_budget
            # Here we set the budget to 0, implying you can't save more than what you have left
            remaining_budget -= savings
        else:
            remaining_budget -= savings

    selected_lifestyle_choices["Savings"] = {"Choice": savings_choice, "Cost": savings}

    # Update sidebar
    remaining_budget_display.markdown(f"### Remaining Monthly Budget: ${remaining_budget:,.2f}")
    if remaining_budget > 0:
        remaining_budget_message.warning(f"You have ${remaining_budget:,.2f} left.")
    elif remaining_budget == 0:
        remaining_budget_message.success("You have balanced your budget perfectly!")
    else:
        # Negative means overspent
        remaining_budget_message.error(f"You have overspent by ${-remaining_budget:,.2f}!")

    # Summary
    st.subheader("Lifestyle Choices Summary")
    for cat, details in selected_lifestyle_choices.items():
        st.write(f"**{cat}:** {details['Choice']} - ${details['Cost']:,.2f}")

    # Step 6: Submit
    st.header("Step 6: Submit Your Budget")
    st.write(f"**Remaining Budget:** ${remaining_budget:,.2f}")

    # Authorize gspread client
    gspread_client = authorize_gspread()
    SHEET_KEY = "1rgS_NxsZjDkPE07kEpuYxvwktyROXKUfYBk-4t9bkqA"

    submit = st.button("Submit")
    if submit:
        # Only allow submission if user has provided name, chosen profession,
        # AND budget is exactly zero (no negative or positive leftover).
        if not participant_name:
            st.info("Please enter your name before submitting.")
        elif not Profession:
            st.info("Please select a profession before submitting.")
        elif remaining_budget < 0:
            st.error(
                f"You have overspent by ${abs(remaining_budget):,.2f}. "
                "Please adjust your expenses or income to balance the budget."
            )
        elif remaining_budget > 0:
            st.error(
                f"You still have ${remaining_budget:,.2f} left. "
                "Please allocate all your income (e.g., increase savings) so your budget is exactly 0."
            )
        else:
            # Build participant data dictionary
            data = {
                "Name": participant_name,
                "Profession": Profession,
                "Marital Status": marital_status,
                "Military Service": military_service_choice,

                # Recommended tax details:
                "Annual Salary": salary,
                "Standard Deduction": standard_deduction,
                "Taxable Income": taxable_income,
                "Federal Tax": federal_tax,
                "State Tax": state_tax,
                "Total Tax": total_tax,
                "Monthly Income After Tax": monthly_income_after_tax,
            }

            # Add each lifestyle category cost EXCEPT for 
            # Marital Status & Military Service (already stored as text):
            for category, details in selected_lifestyle_choices.items():
                if category in ["Military Service"]:
                    continue  # We already have 'Military Service' as text
                data[f"{category} Cost"] = details.get("Cost", 0)
                data[f"{category} Choice"] = details.get("Choice", "")

            data_df = pd.DataFrame([data])

            # Save to Google Sheet
            worksheet = get_google_sheet(gspread_client, SHEET_KEY, "participant_data")
            save_participant_data(data_df, worksheet)


# ----------------------------------------------------------------------------
# 4. EXECUTE MAIN FUNCTION
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
