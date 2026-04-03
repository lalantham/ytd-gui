#!/bin/bash
set -e

echo "======================================"
echo "    YTD-GUI Automated Installer"
echo "======================================"
echo ""

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 could not be found. Please install Python 3."
    exit 1
fi

echo "-> Creating Python virtual environment (venv)..."
python3 -m venv venv

echo "-> Activating virtual environment..."
source venv/bin/activate

echo "-> Upgrading pip..."
pip install --upgrade pip

echo "-> Installing dependencies from requirements.txt..."
pip install -r requirements.txt

echo ""
echo "======================================"
echo "Installation complete!"
echo "======================================"
echo ""
echo "To run the application manually:"
echo "  $ source venv/bin/activate"
echo "  $ python app.py"
echo ""
echo "The application will open on http://localhost:5000"
echo ""
echo "To set up the systemd service for background running:"
echo "  1. Edit ytd-gui.service to ensure the paths match your system."
echo "  2. run: sudo cp ytd-gui.service /etc/systemd/system/"
echo "  3. run: sudo systemctl daemon-reload"
echo "  4. run: sudo systemctl enable --now ytd-gui.service"
echo ""
