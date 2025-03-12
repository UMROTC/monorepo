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

# Initialize session state for submission tracking
if "submitted" not in st.session_state:
    st.session_state.submitted = False

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
        st.success("Your budget has been submitted and saved successfully!")
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

    # Determine base salary based on profession requirements:
    if selected_Profession["Requires School"].lower() == "yes":
        salary = selected_Profession["Savings During School"]
    else:
        salary = selected_Profession["Average Salary"]

    # Step 3: Military Service & Marital Status (Combined Input)
    st.header("Step 3: Choose Your Military Service and Marital Status")
    military_service_choice = st.selectbox(
        "Select your military service option",
        ["No", "Part Time", "Full Time"],
        key="Military_Service"
    )
    marital_status = st.radio("Select your marital status", ["Single", "Married"])

    # No salary adjustment is applied here

    # Calculate tax based on the base salary
    taxable_income, federal_tax, state_tax, total_tax = calculate_tax_by_status(
        salary, marital_status, tax_data
    )
    standard_deduction = tax_data[
        (tax_data["Status"] == marital_status) & (tax_data["Type"] == "Federal")
    ].iloc[0]["Standard Deduction"]

    # Display tax information
    st.write(f"**Annual Salary:** ${salary:,.2f}")
    st.write(f"**Standard Deduction:** ${standard_deduction:,.2f}")
    st.write(f"**Taxable Income:** ${taxable_income:,.2f}")
    st.write(f"**Federal Tax:** ${federal_tax:,.2f}")
    st.write(f"**State Tax:** ${state_tax:,.2f}")
    st.write(f"**Total Tax:** ${total_tax:,.2f}")

    monthly_income_after_tax = (salary - federal_tax - state_tax) / 12
    st.write(f"**Monthly Income After Tax:** ${monthly_income_after_tax:,.2f}")

    # Track user choices in dictionaries
    selected_lifestyle_choices = {}

    # Save military service choice into the lifestyle choices dictionary
    selected_lifestyle_choices["Military Service"] = {
        "Choice": military_service_choice,
        "Cost": 0
    }

    # Define which categories can have "Military" as an option
    allowed_military_part_time = ["Children", "Who Pays for College", "Health Insurance"]
    allowed_military_full_time = ["Housing", "Food", "Children", "Who Pays for College", "Health Insurance"]

    # Step 4: Lifestyle Choices
    st.header("Step 4: Make Lifestyle Choices")

    for category in lifestyle_data["Category"].unique():
        # We'll skip "Savings" until after collecting these
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

        choice = st.selectbox(
            f"Choose your {category.lower()}",
            options,
            key=f"{category}_choice"
        )
        cost_row = lifestyle_data[
            (lifestyle_data["Category"] == category) & (lifestyle_data["Option"] == choice)
        ]

        cost = 0
        if not cost_row.empty and "Monthly Cost" in cost_row:
            try:
                cost = float(cost_row["Monthly Cost"].values[0])
            except ValueError:
                cost = 0

        # Store the chosen cost for now, but do NOT reduce any "running" budget
        selected_lifestyle_choices[category] = {"Choice": choice, "Cost": cost}

    # Step 4b: Savings
    st.subheader("Savings")
    savings_options = lifestyle_data[lifestyle_data["Category"] == "Savings"]["Option"].tolist()
    savings_choice = st.selectbox(
        "Choose your savings option",
        savings_options,
        key="Savings_Choice"
    )

    # Decide the actual savings cost after we see how much the user has left
    calculated_savings = 0.0
    if savings_choice.lower() == "whatever is left":
        # We'll finalize "whatever is left" after we sum all other expenses
        calculated_savings = None  # special marker
    else:
        # Percentage-based or zero
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
                calculated_savings = savings_percentage * monthly_income_after_tax
            else:
                calculated_savings = 0
        except Exception:
            st.error(f"Savings percentage not found or invalid for choice: {savings_choice}")
            calculated_savings = 0

    selected_lifestyle_choices["Savings"] = {"Choice": savings_choice, "Cost": 0}  # We'll finalize cost below

    # -----------------------------
    # Compute final budget
    # -----------------------------

    # 1) Sum up all non-savings costs
    total_expenses = sum(
        details["Cost"] 
        for cat, details in selected_lifestyle_choices.items() 
        if cat not in ["Military Service", "Savings"]
    )

    # 2) If the user chose "whatever is left" for savings,
    #    then "calculated_savings" is None. We compute after expenses:
    if calculated_savings is None:
        if (monthly_income_after_tax - total_expenses) <= 0:
            st.warning("You have no remaining budget to save—your expenses exceed your income.")
            calculated_savings = 0
        else:
            calculated_savings = (monthly_income_after_tax - total_expenses)

    # 3) Final remaining budget after expenses + savings
    remaining_budget = monthly_income_after_tax - total_expenses - calculated_savings

    # 4) Update the "Savings" cost in the dictionary
    selected_lifestyle_choices["Savings"]["Cost"] = calculated_savings

    # -----------------------------
    # Sidebar & Summary
    # -----------------------------
    st.sidebar.header("Remaining Monthly Budget")
    remaining_budget_display = st.sidebar.empty()
    remaining_budget_message = st.sidebar.empty()

    remaining_budget_display.markdown(f"### Remaining Monthly Budget: ${remaining_budget:,.2f}")

    if remaining_budget > 0:
        remaining_budget_message.warning(f"You have ${remaining_budget:,.2f} left.")
    elif remaining_budget == 0:
        remaining_budget_message.success("You have balanced your budget!")
    else:
        remaining_budget_message.error(f"You have overspent by ${-remaining_budget:,.2f}!")

    st.subheader("Lifestyle Choices Summary")
    for cat, details in selected_lifestyle_choices.items():
        st.write(f"**{cat}:** {details['Choice']} - ${details['Cost']:,.2f}")

    # -----------------------------
    # Step 5: Submit
    # -----------------------------
    st.header("Step 5: Submit Your Budget")
    st.write(f"**Remaining Budget:** ${remaining_budget:,.2f}")

    if st.session_state.submitted:
        st.info("You have already submitted your budget. Thank you!")
    else:
        submit = st.button("Submit")
        if submit:
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
                    "Annual Salary": salary,
                    "Standard Deduction": standard_deduction,
                    "Taxable Income": taxable_income,
                    "Federal Tax": federal_tax,
                    "State Tax": state_tax,
                    "Total Tax": total_tax,
                    "Monthly Income After Tax": monthly_income_after_tax,
                }

                # Add each lifestyle category cost and choice (except Military Service)
                for category, details in selected_lifestyle_choices.items():
                    if category == "Military Service":
                        continue
                    data[f"{category} Cost"] = details["Cost"]
                    data[f"{category} Choice"] = details["Choice"]

                data_df = pd.DataFrame([data])

                # Save original submission to Google Sheet
                gspread_client = authorize_gspread()
                SHEET_KEY = "1rgS_NxsZjDkPE07kEpuYxvwktyROXKUfYBk-4t9bkqA"
                worksheet = get_google_sheet(gspread_client, SHEET_KEY, "participant_data")
                save_participant_data(data_df, worksheet)

                # Mark as submitted
                st.session_state.submitted = True

                # ----------------------------------------------------------------------
                # Create -mil Doppelganger
                # ----------------------------------------------------------------------
                # Duplicate the original data dictionary for the doppelganger record
                doppel_data = data.copy()

                # Update the name field to include "-mil" suffix
                doppel_data["Name"] = f"{participant_name}-mil"

                # Force military service to "Part Time"
                doppel_data["Military Service"] = "Part Time"

                # Override specific lifestyle choices if applicable:
                # a. For Children: if cost is nonzero, set choice to "Military"
                if "Children Cost" in doppel_data and float(doppel_data["Children Cost"]) != 0:
                    doppel_data["Children Choice"] = "Military"
                # b. Who Pays for College: set choice to "Military"
                if "Who Pays for College Choice" in doppel_data:
                    doppel_data["Who Pays for College Choice"] = "Military"
                # c. Health Insurance: set choice to "Military"
                if "Health Insurance Choice" in doppel_data:
                    doppel_data["Health Insurance Choice"] = "Military"
                    # Update the Health Insurance cost using the cost for the Military option
                    mil_health_row = lifestyle_data[
                        (lifestyle_data["Category"] == "Health Insurance") &
                        (lifestyle_data["Option"] == "Military")
                    ]
                    if not mil_health_row.empty:
                        try:
                            mil_health_cost = float(mil_health_row["Monthly Cost"].values[0])
                        except ValueError:
                            mil_health_cost = 0
                        doppel_data["Health Insurance Cost"] = mil_health_cost

                doppel_df = pd.DataFrame([doppel_data])
                # Save the doppelganger record to the same Google Sheet
                save_participant_data(doppel_df, worksheet)

if __name__ == "__main__":
    main()
