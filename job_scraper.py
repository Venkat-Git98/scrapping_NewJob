import requests
from bs4 import BeautifulSoup
import json
import time
import smtplib
from email.message import EmailMessage
import schedule # For running tasks periodically
import logging
import re
import os # For environment variables and file operations

# --- Configuration ---
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

SCRAPER_CONFIGS = [
    {
        "url": "https://www.linkedin.com/jobs/search/?currentJobId=4228089895&distance=25&f_E=1%2C2%2C3%2C4&f_TPR=r7200&geoId=103644278&keywords=machine%20learning%20engineer&origin=JOB_SEARCH_PAGE_JOB_FILTER&sortBy=R&spellCorrectionEnabled=true", # Your actual URL
        "data_file": "linkedin_mle_jobs.json", # Will be created in the same dir as script
        "search_name": "Machine Learning Engineer"
    },
    {
        "url": "https://www.linkedin.com/jobs/search/?keywords=Data%20Scientist&location=United%20States&geoId=103644278&f_TPR=r7200&f_E=1%2C2%2C3%2C4&position=1&pageNum=0", # Your actual URL
        "data_file": "linkedin_ds_jobs.json", # Will be created in the same dir as script
        "search_name": "Data Scientist"
    },
    # Add more scraper configurations here
]

JOB_LIST_SELECTOR = "ul.jobs-search__results-list"
JOB_CARD_SELECTOR = "li"
JOB_TITLE_SELECTOR = "h3.base-search-card__title"
JOB_URL_SELECTOR = "a.base-card__full-link"
JOB_ID_ELEMENT_SELECTOR = "div.base-search-card"
JOB_ID_ATTRIBUTE = "data-entity-urn"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") # Ensure this is fetched from env for security
EMAIL_SENDER = os.getenv("EMAIL_SENDER",)
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

EMAIL_FILTER_KEYWORDS = [
    "data", "machine learning", "ml ", " ml", " ai ", " ai", "artificial intelligence",
    "scientist", "applied scientist", "research scientist", "data engineer", "ml engineer",
    "analytics", "statistician", "quantitative"
]

SCHEDULE_INTERVAL_MINUTES = 2

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions ---

def load_previous_jobs(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            previous_jobs = json.load(f)
        logging.info(f"Successfully loaded {len(previous_jobs)} previous jobs from {filepath}")
        return previous_jobs
    except FileNotFoundError:
        logging.info(f"Job data file {filepath} not found. Starting with an empty job list.")
        return []
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {filepath}. Starting with an empty job list.")
        return []

def save_jobs(filepath, jobs):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(jobs, f, indent=4)
        logging.info(f"Successfully saved {len(jobs)} jobs to {filepath}")
    except IOError as e:
        logging.error(f"Could not save jobs to {filepath}: {e}")

def parse_job_id(raw_id_attribute_val, job_url):
    job_id = None
    id_source = "unknown"
    if raw_id_attribute_val:
        if 'urn:li:jobPosting:' in raw_id_attribute_val:
            job_id = raw_id_attribute_val.split(':')[-1]
            id_source = 'urn'
        else:
            job_id = raw_id_attribute_val
            id_source = 'attribute_direct'
    if not job_id and job_url != "N/A":
        try:
            match = re.search(r'/(\d{7,})', job_url.split('?')[0])
            if match:
                job_id = match.group(1)
                id_source = 'url_regex'
            else:
                path_segments = job_url.split('?')[0].split('/')
                for segment in reversed(path_segments):
                    if segment.isdigit() and len(segment) > 6: job_id = segment; id_source = 'url_segment_numeric'; break
                    elif '-' in segment:
                        id_part = segment.split('-')[-1]
                        if id_part.isdigit() and len(id_part) > 6: job_id = id_part; id_source = 'url_segment_slug'; break
        except Exception as e: logging.debug(f"Error parsing job ID from URL {job_url}: {e}")
    if not job_id: job_id = job_url; id_source = 'url_fallback'
    return str(job_id), id_source

def parse_jobs(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    parsed_jobs_list = []
    job_list_container = soup.select_one(JOB_LIST_SELECTOR)
    if not job_list_container:
        logging.warning(f"No job list container found with selector: {JOB_LIST_SELECTOR}")
        return []
    job_cards = job_list_container.select(JOB_CARD_SELECTOR)
    for card_index, card in enumerate(job_cards): # Added card_index for logging
        title_element = card.select_one(JOB_TITLE_SELECTOR)
        url_element = card.select_one(JOB_URL_SELECTOR)
        title = title_element.get_text(strip=True) if title_element else "N/A"
        job_page_url = url_element['href'] if url_element and url_element.has_attr('href') else "N/A"
        if job_page_url.startswith("/jobs/view/"): job_page_url = "https://www.linkedin.com" + job_page_url
        raw_id_attribute_val = None
        id_element = card.select_one(JOB_ID_ELEMENT_SELECTOR) if JOB_ID_ELEMENT_SELECTOR else card
        if id_element and id_element.has_attr(JOB_ID_ATTRIBUTE):
            raw_id_attribute_val = id_element.get(JOB_ID_ATTRIBUTE)
        job_id, id_source = parse_job_id(raw_id_attribute_val, job_page_url)
        if title != "N/A" and job_page_url != "N/A":
            parsed_jobs_list.append({"id": job_id, "title": title, "url": job_page_url, "id_source": id_source})
        else:
            logging.warning(f"Skipped card #{card_index+1} due to missing title or URL. Title: '{title}', URL: '{job_page_url}'")
    logging.info(f"Parsed {len(parsed_jobs_list)} jobs from HTML content.")
    return parsed_jobs_list

def send_email_notification(new_jobs_list):
    if not new_jobs_list:
        logging.info("No new relevant jobs matching keywords to send email for.")
        return
    subject = f"LinkedIn Job Alert:New Relevant Job(s) Found!"
    body_parts = [f"Found {len(new_jobs_list)} new job posting(s) matching your keywords across your searches:"]
    for job in new_jobs_list:
        body_parts.append(f"\n--- Job from: {job.get('search_source_name', 'Unknown Search')} ---")
        body_parts.append(f"Title: {job['title']}")
        body_parts.append(f"URL: {job['url']}")
        if job.get('id_source') != 'url_fallback' and job['id'] != job['url']:
             body_parts.append(f"Parsed ID: {job['id']} (Source: {job.get('id_source', 'URN/Parsed')})")
    body_parts.append("\n\nHappy job hunting!")
    body = "\n".join(body_parts)
    msg = EmailMessage(); msg.set_content(body)
    msg['Subject'] = subject; msg['From'] = EMAIL_SENDER; msg['To'] = EMAIL_RECEIVER
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo(); server.starttls(); server.ehlo()
            server.login(SMTP_USERNAME, SMTP_PASSWORD); server.send_message(msg)
        logging.info(f"Email notification sent successfully to {EMAIL_RECEIVER} for {len(new_jobs_list)} new relevant jobs.")
    except smtplib.SMTPAuthenticationError as e:
        logging.error(f"SMTP Authentication Error: {e}. Check SMTP_USERNAME/SMTP_PASSWORD and Gmail App Password settings.")
    except smtplib.SMTPConnectError as e:
        logging.error(f"SMTP Connection Error: {e}. Could not connect to {SMTP_SERVER}:{SMTP_PORT}.")
    except smtplib.SMTPServerDisconnected as e:
        logging.error(f"SMTP Server Disconnected: {e}.")
    except Exception as e: logging.error(f"Failed to send email: {e}")

def process_job_search(search_config):
    search_url, data_file, search_name = search_config["url"], search_config["data_file"], search_config["search_name"]
    logging.info(f"--- Starting job scraping process for: {search_name} (URL: {search_url}) ---")
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(search_url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch LinkedIn job page for {search_name}: {e}")
        return []
    current_jobs_parsed = parse_jobs(response.text)
    if not current_jobs_parsed:
        logging.info(f"No jobs parsed from the page for {search_name}.")
        return []
    for job in current_jobs_parsed: job['search_source_name'] = search_name
    previous_jobs = load_previous_jobs(data_file) # Will be [] if file was deleted by midnight task
    previous_job_ids = {job['id'] for job in previous_jobs}
    new_jobs_this_search = []
    for job in current_jobs_parsed:
        if job['id'] not in previous_job_ids:
            new_jobs_this_search.append(job)
            logging.info(f"NEW JOB ({search_name}): '{job['title']}' (ID: {job['id']}, Source: {job['id_source']}) - {job['url']}")
    save_jobs(data_file, current_jobs_parsed)
    logging.info(f"Scraping for {search_name} done. Found {len(new_jobs_this_search)} new jobs for this specific search.")
    return new_jobs_this_search

def delete_state_files_task():
    """Deletes all configured job state JSON files."""
    logging.info("Midnight task: Attempting to delete job state JSON files...")
    for config in SCRAPER_CONFIGS:
        filepath = config.get("data_file")
        if filepath:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    logging.info(f"Deleted state file: {filepath}")
                else:
                    logging.info(f"State file not found (already deleted or never created): {filepath}")
            except Exception as e:
                logging.error(f"Error deleting state file {filepath}: {e}")
        else:
            logging.warning(f"No 'data_file' defined for a scraper config: {config.get('search_name', 'Unnamed')}")
    logging.info("Midnight file deletion task completed.")

def run_all_scrapers_and_notify():
    logging.info("===== Starting all scraping processes =====")
    all_new_jobs_from_all_searches = []
    for i, config in enumerate(SCRAPER_CONFIGS):
        new_jobs = process_job_search(config)
        all_new_jobs_from_all_searches.extend(new_jobs)
        if i < len(SCRAPER_CONFIGS) - 1: time.sleep(5)

    if not all_new_jobs_from_all_searches:
        logging.info("No new jobs found from any scraper during this cycle.")
    else:
        unique_new_jobs = []
        seen_job_ids_for_notification = set()
        for job in all_new_jobs_from_all_searches:
            if job['id'] not in seen_job_ids_for_notification:
                unique_new_jobs.append(job)
                seen_job_ids_for_notification.add(job['id'])
            else:
                logging.info(f"Duplicate job ID {job['id']} ('{job['title']}') from source '{job['search_source_name']}' already processed this run. Notifying once.")
        
        if not unique_new_jobs:
            logging.info("No new unique jobs after deduplication for this run.")
        else:
            logging.info(f"Total unique new jobs found across all searches this run: {len(unique_new_jobs)}")
            jobs_for_email_notification = []
            logging.info(f"Applying email keyword filter. Keywords: {EMAIL_FILTER_KEYWORDS}")
            for job in unique_new_jobs:
                title_lower = job['title'].lower()
                matched_by_keyword = False
                for kw in EMAIL_FILTER_KEYWORDS:
                    kw_lower = kw.lower().strip()
                    if not kw_lower: continue
                    if len(kw_lower) <= 3:
                        if re.search(r'\b' + re.escape(kw_lower) + r'\b', title_lower): matched_by_keyword = True; break
                    elif kw_lower in title_lower: matched_by_keyword = True; break
                if matched_by_keyword:
                    jobs_for_email_notification.append(job)
                    logging.info(f"Job '{job['title']}' (from {job['search_source_name']}) matches email keywords for notification.")
                # else: # Can be verbose
                #     logging.debug(f"Job '{job['title']}' (from {job['search_source_name']}) does NOT match email keywords.")
            
            if jobs_for_email_notification:
                send_email_notification(jobs_for_email_notification)
            else:
                logging.info("No new unique jobs matched the email filter keywords for notification.")
    logging.info("===== All scraping processes completed =====")

# --- Main Execution ---
if __name__ == "__main__":
    logging.info("Script starting...")

    # Retrieve sensitive credentials from environment variables
    # The defaults in the config section are for local testing if env vars are not set
    actual_smtp_username = os.getenv("SMTP_USERNAME", SMTP_USERNAME)
    actual_smtp_password = os.getenv("SMTP_PASSWORD") # This MUST be set in Railway
    actual_email_sender = os.getenv("EMAIL_SENDER", EMAIL_SENDER)
    actual_email_receiver = os.getenv("EMAIL_RECEIVER", EMAIL_RECEIVER)

    # Update global config if environment variables are found (for functions using them directly)
    SMTP_USERNAME = actual_smtp_username
    SMTP_PASSWORD = actual_smtp_password
    EMAIL_SENDER = actual_email_sender
    EMAIL_RECEIVER = actual_email_receiver

    if not SMTP_PASSWORD: # Check after attempting to load from env
        logging.error("CRITICAL: SMTP_PASSWORD is not set (missing environment variable on Railway or empty in script). Exiting.")
        exit(1)
    if "YOUR_GMAIL_APP_PASSWORD" in SMTP_PASSWORD or SMTP_PASSWORD == "osly quyc zgnv tork" and not os.getenv("SMTP_PASSWORD"): # Check for placeholder if not overridden by env
        logging.warning("WARNING: SMTP_PASSWORD might be a placeholder or default script value. Ensure it's correctly set via environment variables on Railway.")
        # For a critical password, you might want to exit(1) here if a placeholder is detected and it's not from env.
        # However, the os.getenv("SMTP_PASSWORD") check is primary for Railway.

    if not SCRAPER_CONFIGS:
        logging.error("CRITICAL: SCRAPER_CONFIGS list is empty.")
        exit(1)
    for i, config in enumerate(SCRAPER_CONFIGS):
        if not config.get("url") or "YOUR_LINKEDIN_JOB_SEARCH_URL" in config.get("url", ""):
            logging.error(f"CRITICAL: URL for scraper config #{i+1} ('{config.get('search_name', 'Unnamed')}') is not set properly.")
            exit(1)

    logging.info(f"LinkedIn Job Scraper started. Checking for jobs every {SCHEDULE_INTERVAL_MINUTES} minutes.")
    logging.info(f"Email notifications will be sent if job titles contain any of: {EMAIL_FILTER_KEYWORDS}")
    for i, config in enumerate(SCRAPER_CONFIGS):
        logging.info(f"--- Configured Scraper #{i+1} ---")
        logging.info(f"Search Name: {config['search_name']}")
        logging.info(f"URL: {config['url']}")
        logging.info(f"Data File: {config['data_file']}")
    logging.info(f"Notifications will be sent from {EMAIL_SENDER} to: {EMAIL_RECEIVER}")

    run_all_scrapers_and_notify()

    schedule.every(SCHEDULE_INTERVAL_MINUTES).minutes.do(run_all_scrapers_and_notify)
    logging.info(f"Scraping scheduled every {SCHEDULE_INTERVAL_MINUTES} minutes.")

    # Schedule daily file deletion at midnight (server time, likely UTC on Railway)
    # Example: "00:00" for midnight. If you need a specific timezone, you'd use pytz.
    # For Railway, the server time is UTC. So "00:00" is UTC midnight.
    schedule.every().day.at("00:00").do(delete_state_files_task)
    logging.info("Daily state file deletion scheduled at 00:00 (server/UTC time).")

    logging.info("Scheduler started. Waiting for the next scheduled run...")
    while True:
        schedule.run_pending()
        time.sleep(1)