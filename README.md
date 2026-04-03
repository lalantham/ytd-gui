# YTD-GUI

A beautiful, automated web interface for downloading media using `yt-dlp`. 

## Features
- **Clean Interface**: Easy-to-use web application for downloading content.
- **Batch Downloads**: Paste multiple URLs separated by commas or on new lines to download them at once. Options to zip all downloads together.
- **Qualities and Formats**: Fetch available video qualities dynamically. Direct download of MP3s (Audio only mode).
- **Live Progress**: Real-time progress updates, showing current phase, speed, downloaded amount, and ETA.
- **Browser Downloads**: In-progress files are shielded; finished downloads are seamlessly served to your browser as standard file downloads.

## Prerequisites
- **Python 3.x**
- **FFmpeg** (Highly recommended for merging video and audio, and extracting MP3s)

## Installation

This application uses Python virtual environments for a clean setup.

### Automated Setup (Linux/macOS)

You can use the provided automated installer script to quickly set up your environment:

```bash
chmod +x install.sh
./install.sh
```

This script will automatically:
1. Create a localized Python virtual environment (`venv`).
2. Activate the environment.
3. Install all required Python packages.

### Manual Setup

If you prefer to set it up manually:

1. Create a Python virtual environment:
   ```bash
   python3 -m venv venv
   ```
2. Activate the virtual environment:
   ```bash
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the App

Activate the virtual environment and run the main entry point:

```bash
source venv/bin/activate
python app.py
```

The web server will start running. Navigate to `http://localhost:5000` in your web browser.

## Running Background Service (systemd)

If you'd like to run the app silently as a Linux background service, a `ytd-gui.service` template is included.

1. Ensure the paths inside `ytd-gui.service` point exactly to where this repository is located on your machine.
2. Install and activate it:

```bash
sudo cp ytd-gui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ytd-gui.service
```

## Disclaimer
This project is an open-source web wrapper for `yt-dlp`. Ensure you respect copyright laws and the terms of service of the platforms you download content from.
