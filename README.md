# Automated Job Posting Monitor & Notifier

## Overview

This project is an automated script designed to monitor various job posting websites for new job applications. It helps users stay updated on the latest opportunities relevant to their search criteria without needing to manually check multiple sites.

## Key Features

* **Automated Monitoring:** Regularly scrapes configured job sites for the latest listings.
* **Frequent Checks:** Scans for new job postings every 2 minutes.
* **Email Notifications:** Sends an email alert when new, relevant job applications are identified.
* **Keyword Filtering:** Filters newly found job postings based on user-defined keywords to ensure notifications are targeted and relevant.
* **Duplicate Prevention:** Intelligently tracks previously seen jobs for each configured search to only notify about genuinely new entries.
* **Multi-Search Capability:** Can monitor multiple distinct job search configurations simultaneously from different sources or for different roles.

## How It Works (Briefly)

The script periodically fetches data from the specified job site search URLs. It then compares the current listings with a record of jobs seen in previous checks for each individual search. If new, unique job postings are identified, they are further filtered by a predefined list of keywords. Jobs that match these criteria trigger an email notification, delivering the details (like job title and URL) directly to the configured recipient.

## Current Status

* This automated monitoring system is **currently deployed and actively running**. It checks the configured job searches every 2 minutes and dispatches email notifications for new, relevant findings.

---

*This script uses local JSON files to keep track of seen jobs for each search configuration to ensure only new jobs are reported. Sensitive information like email credentials should be managed via environment variables when deployed.*