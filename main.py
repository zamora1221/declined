import os
import base64
import streamlit as st
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.firefox.service import Service
from webdriver_manager.firefox import GeckoDriverManager
import pandas as pd
import time
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import csv

st.title("Jail Bond Record Search")

uploaded_file = st.file_uploader("Choose a file")
county = st.selectbox("Select County", ["Guadalupe", "Comal", "Hays", "Williamson"])
start_button = st.button("Start")

class AnyOfTheseElementsLocated:
    def __init__(self, *locators):
        self.locators = locators

    def __call__(self, driver):
        for locator in self.locators:
            try:
                element = driver.find_element(*locator)
                print(f"Found element: {locator}")
                return element
            except NoSuchElementException:
                pass
        return False

def read_names_from_xlsx(file_path):
    df = pd.read_excel(file_path)
    df = df.drop_duplicates()
    names = []
    suffixes = ["Jr.", "Sr.", "I", "II", "III"]

    df['People::D.O.B.'] = pd.to_datetime(df['People::D.O.B.'], errors='coerce')

    for index, row in df.iterrows():
        if pd.notnull(row['People::Name Full']):
            full_name = row['People::Name Full'].strip().split()
            first_name = full_name[0]

            if len(full_name) == 2:
                last_name = full_name[-1]
            elif len(full_name) == 3 and len(full_name[1]) == 1:
                last_name = full_name[-1]
            else:
                if len(full_name) > 1 and full_name[-2] in suffixes:
                    last_name = " ".join(full_name[-3:-1])
                else:
                    last_name = " ".join(full_name[-3:])
        else:
            first_name = ''
            last_name = ''

        if pd.isnull(row['People::D.O.B.']):
            dob = ''
        else:
            dob = row['People::D.O.B.'].strftime('%m/%d/%Y')

        name = {'first_name': first_name, 'last_name': last_name, 'dob': dob}
        names.append(name)
    return names

def write_cases_to_csv(cases, file_path):
    with open(file_path, mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["People::Name Full", "People::D.O.B.", "Case Number", "Status"])
        for case in cases:
            full_name = "{} {}".format(case["first_name"], case["last_name"])
            writer.writerow([full_name, case["dob"], case["case_number"], case["status"]])

def write_no_case_to_csv(no_case, file_path):
    with open(file_path, mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["People::Name Full", "People::D.O.B."])
        for case in no_case:
            full_name = "{} {}".format(case["first_name"], case["last_name"])
            writer.writerow([full_name, case["dob"]])

def search_form(driver, last_name, first_name, dob=''):
    last_name_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "LastName")))
    first_name_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "FirstName")))
    search_button = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "SearchSubmit")))

    last_name_input.clear()
    first_name_input.clear()
    last_name_input.send_keys(last_name)
    first_name_input.send_keys(first_name)

    if dob:
        dob_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "DateOfBirth")))
        dob_input.clear()
        dob_input.send_keys(dob)

    search_button.click()

def has_declined_status(html_content):
    return "Declined" in html_content

def has_posted_status(html_content):
    return "Posted" in html_content

def get_jail_bond_records(driver, county, last_name, first_name, cases, no_case, dob=''):
    search_url = {
        "Guadalupe": "https://portal-txguadalupe.tylertech.cloud/PublicAccess/default.aspx",
        "Comal": "http://public.co.comal.tx.us/default.aspx",
        "Hays": "https://public.co.hays.tx.us/default.aspx",
        "Williamson": "https://judicialrecords.wilco.org/PublicAccess/default.aspx"
    }[county]

    driver.get(search_url)
    time.sleep(2)

    if county in ["Guadalupe", "Comal", "Hays", "Williamson"]:
        print("Looking for the Jail Bond Records link...")
        for _ in range(5):
            try:
                jail_bond_records_link = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.LINK_TEXT, "Jail Bond Records")))
                jail_bond_records_link.click()
                break
            except TimeoutException:
                print("Timed out waiting for 'Jail Bond Records' link, retrying...")
                driver.refresh()

        # Specific code for Guadalupe
        if county == "Guadalupe":
            for _ in range(5):
                try:
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "SearchBy")))
                    break
                except TimeoutException:
                    print("Timed out waiting for element with ID 'SearchBy', refreshing...")
                    driver.refresh()
            search_type_dropdown = Select(driver.find_element(By.ID, "SearchBy"))
            search_type_dropdown.select_by_visible_text("Defendant")

    search_form(driver, last_name, first_name, dob)
    case_record = {'first_name': first_name, 'last_name': last_name, 'dob': dob, 'status': '', 'case_number': ''}
    print("Waiting for search results...")

    declined_div_locator = (By.XPATH, "//div[contains(text(), 'Declined')]")
    posted_div_locator = (By.XPATH, "//div[contains(text(), 'Posted')]")
    no_cases_matched_locator = (By.XPATH, "//span[contains(text(), 'No cases matched your search criteria.')]")

    try:
        WebDriverWait(driver, 10).until(AnyOfTheseElementsLocated(declined_div_locator, posted_div_locator, no_cases_matched_locator))
        html_content = driver.page_source

        if has_declined_status(html_content) and not has_posted_status(html_content):
            # Case is declined
            case_record['status'] = 'Declined'
            print(f"{last_name}, {first_name} case is Declined.")
            return case_record, True, None
        elif not has_declined_status(html_content) and has_posted_status(html_content):
            # Case is Active
            case_record['status'] = 'Active'
            print(f"{last_name}, {first_name} case is Active.")
            return case_record, True, None
        else:
            # Neither condition met
            print(f"{last_name}, {first_name} case status is unknown.")
            return None, False, None
    except TimeoutException:
        print(f"{last_name}, {first_name} - No cases matched.")
        return None, False, None

    return None, False, None

def download_csv(file_path):
    with open(file_path, 'rb') as f:
        data = f.read()
    b64 = base64.b64encode(data).decode('UTF-8')
    href = f'<a href="data:file/csv;base64,{b64}" download="{file_path}">Download CSV file</a>'
    st.markdown(href, unsafe_allow_html=True)

if uploaded_file is not None and county and start_button:
    file_path = os.path.join(os.getcwd(), uploaded_file.name)
    with open(file_path, 'wb') as f:
        f.write(uploaded_file.getbuffer())

    st.write(f"File uploaded successfully: {uploaded_file.name}")
    st.write("Starting the process...")

    firefox_options = webdriver.FirefoxOptions()
    firefox_options.add_argument("--headless")
    driver = webdriver.Firefox(service=Service(GeckoDriverManager().install()), options=firefox_options)

    cases = []
    no_case = []
    names = read_names_from_xlsx(file_path)

    total_names = len(names)
    progress_increment = 100 / total_names if total_names else 1
    current_progress = 0

    progress_bar = st.progress(0)

    for name in names:
        first_name = name['first_name']
        last_name = name['last_name']
        dob = name['dob']

        case_record, is_found, _ = get_jail_bond_records(driver, county, last_name, first_name, cases, no_case, dob)
        if is_found:
            cases.append(case_record)
        else:
            no_case.append(name)

        current_progress += progress_increment
        progress_bar.progress(int(current_progress))

    driver.quit()
    write_cases_to_csv(cases, 'cases.csv')
    write_no_case_to_csv(no_case, 'no_case.csv')

    st.write('Process complete.')
    st.write(f'Cases found: {len(cases)}')
    st.write(f'No cases found: {len(no_case)}')

    st.markdown("### Download cases")
    download_csv('cases.csv')

    st.markdown("### Download no cases found")
    download_csv('no_case.csv')

else:
    st.write('Upload a file, select a county, and click Start.')
