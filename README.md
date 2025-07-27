# 🌊 SurfShark Wireproxy Manager

<div align="center">

**A modern GUI application for converting SurfShark WireGuard connections to SOCKS5 proxies**

![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

*Transform your SurfShark WireGuard VPN into multiple SOCKS5 proxies with an intuitive GUI*

</div>

---

This is a **GUI frontend for wireproxy** specifically designed for SurfShark users. It automatically fetches all SurfShark server locations and allows you to create multiple SOCKS5 proxies, each connected to different geographic locations.

### **Key Features:**
- 🌍 **Global Server Access** - Connect to any SurfShark server location worldwide
- 🔄 **Multiple Proxies** - Run several SOCKS5 proxies simultaneously on different ports
- 💾 **State Persistence** - Automatically restores your proxy configurations
- 🔧 **System Tray Integration** - Minimize to system tray for background operation

---

## ⚠️ **Important Security Notes**

> **For Local Use Only**
> 
> - SOCKS5 proxies have **no authentication** (suitable for localhost only)
> - Configuration files store keys in **plain text** (local security model)
> - Designed for **personal/development use**, not production environments

---

##  **Quick Start Guide**

### **Prerequisites**
- Python 3.7 or higher
- Active SurfShark subscription
- Windows is tested but you can try on Linux

### **Step 1: Get Your SurfShark Keys**

1. Go to [my.surfshark.com](https://my.surfshark.com)
2. Click **"Manual Setup"**
3. Select **"Desktop or mobile"**
4. Click **"I don't have a key pair"**  
   ![Step 1](https://github.com/sudozid/WireProxy_SurfShark_GUI/raw/main/README_IMAGES/1.png)
5. Click **"Generate a new key pair"**
6. Enter a name and click **"Next"**  
   ![Step 2](https://github.com/sudozid/WireProxy_SurfShark_GUI/raw/main/README_IMAGES/2.png)
7. **Keep this window open** - you'll need these keys!

### **Step 2: Installation**

**Note:** If you do not have git installed, you can simply download the zip from https://github.com/sudozid/WireProxy_SurfShark_GUI - Click on the green 'Code' button and select "Download ZIP", extract using 7zip or WinRAR, then skip the git clone step.

#### **Option A: Simple Installation**
```bash
# Clone the repository
git clone https://github.com/sudozid/WireProxy_SurfShark_GUI.git
cd WireProxy_SurfShark_GUI

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

#### **Option B: Virtual Environment (Recommended)**
```bash
# Clone and navigate
git clone https://github.com/sudozid/WireProxy_SurfShark_GUI.git
cd WireProxy_SurfShark_GUI

# Create and activate virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install and run
pip install -r requirements.txt
python main.py
```

### **Step 3: Configuration**

1. **Launch the application**
2. **Enter your keys** - Paste your SurfShark public and private keys, then click "Update Keys"  
   ![Step 3](https://github.com/sudozid/WireProxy_SurfShark_GUI/raw/main/README_IMAGES/3.png)
3. **Add a proxy**:
   - Select a country/location (e.g., "United Kingdom")
   - Choose a port (e.g., 6000)
   - Click "Add Proxy"  
   ![Step 4](https://github.com/sudozid/WireProxy_SurfShark_GUI/raw/main/README_IMAGES/4.png)
4. **Start the proxy** - Click the "Start" button after selecting the proxy from the list, it will show "RUNNING"  
   ![Step 5](https://github.com/sudozid/WireProxy_SurfShark_GUI/raw/main/README_IMAGES/5.png)
5. **Test it works**:
   ```bash
   curl --socks5 127.0.0.1:6000 http://httpbin.org/ip
   ```
   ![Step 6](https://github.com/sudozid/WireProxy_SurfShark_GUI/raw/main/README_IMAGES/6.png)

---

## 📦 **Creating Standalone Executable (Windows)**

You can create a standalone Windows executable that doesn't require Python to be installed:

### **Prerequisites for Building:**
```bash
pip install pyinstaller
```

### **Build Instructions:**

#### **Simple One-File Executable:**
```bash
# Activate your virtual environment first
venv\Scripts\activate

# Create a single executable file
pyinstaller --onefile --windowed --name "WireProxy_SurfShark_GUI" main.py
```

#### **Directory-based Build (Faster startup):**
```bash
# Creates a folder with executable and dependencies
pyinstaller --windowed --name "WireProxy_SurfShark_GUI" main.py
```

### **What You Get:**
- **One-file build**: `dist/WireProxy_SurfShark_GUI.exe` (single file, slower startup)
- **Directory build**: `dist/WireProxy_SurfShark_GUI/` folder with `.exe` and libraries

### **Distribution:**
- The executable is **portable** - no installation required
- Users don't need Python installed
- Include wireproxy binary in the same folder, or let the app download it automatically


### **Linux/macOS Executables:**
```bash
# Same commands should work on Linux/macOS
pyinstaller --onefile --windowed main.py

# Linux users might need:
sudo apt-get install binutils

```

**Note:** I haven't tested Linux/macOS executable creation.

---

## 📱 **Platform Support**

| Platform | Status | Notes |
|----------|--------|-------|
| **Windows 10/11** | ✅ Fully Tested | Primary development platform |
| **Linux** | Idk | Ubuntu 20.04+, other distributions |
| **macOS** | Idk | macOS 10.15+ |

### **Platform-Specific Setup**

#### **Linux Users:**
```bash
# Install tkinter if missing
sudo apt-get install python3-tk libappindicator3-1
```

---

## 📁 **Project Structure**

```
WireProxy_SurfShark_GUI/
├── README_IMAGES		   # Readme images
├── LICENSE 			   # MIT License
├── main.py          # Main application
├── requirements.txt              # Python dependencies
├── README.md                    # This file
├── wireproxy_settings.json     # App settings (auto-generated)
├── wireproxy_state.json         # Proxy state (auto-generated)
├── wireproxy_servers_cache.json # Server cache (auto-generated)
```

---

## **Configuration Files**

The application automatically creates and manages these files:

- **`wireproxy_settings.json`** - Application preferences
- **`wireproxy_state.json`** - Active proxy configurations and keys
- **`wireproxy_servers_cache.json`** - Cached server list (refreshed every 24h)

---

## **Troubleshooting**

### **Common Issues:**

#### **"wireproxy executable not found"**
The app will automatically offer to download wireproxy for you, if doesn't work properly, you can:
- Download from [wireproxy releases](https://github.com/whyvl/wireproxy/releases)
- Place the executable in your PATH or same directory

#### **"Module not found" errors**
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### **GUI doesn't appear (Linux)**
```bash
sudo apt-get install python3-tk
```

#### **Proxy not working**
1. Check if wireproxy process is running
2. Verify your SurfShark keys are correct
3. Test with: `curl --socks5 127.0.0.1:6000 http://httpbin.org/ip`

#### **PyInstaller Issues:**
```bash
# If build fails, try:
pip install --upgrade pyinstaller
pip install --upgrade setuptools

# For "module not found" during build:
pyinstaller --hidden-import=missing_module_name main.py
```

---

## 🙏 **Credits & Acknowledgments**

This project was made possible thanks to:

### **Core Dependencies:**
- **[wireproxy](https://github.com/whyvl/wireproxy)** by whyvl - The core SOCKS5 proxy implementation that makes this all possible
- **[SurfShark](https://surfshark.com)** - VPN service provider with WireGuard support

### **Development Assistance:**
- **Large Language Models** - Significant code generation and development assistance from:
  - **Claude** (Anthropic)
  - **ChatGPT** (OpenAI) 
  - **DeepSeek**

### **Open Source Libraries:**
- **Python** - Core programming language
- **tkinter** - GUI framework
- **requests** - HTTP library for API calls
- **psutil** - System and process utilities
- **pystray** - System tray integration
- **Pillow** - Image processing

---

## 📄 **License**

**MIT License** - You can do anything with this code without giving credit.

---

## **Disclaimer**

> **Important Legal Notice**
> 
> This program was developed with assistance from large language models (Claude, ChatGPT, DeepSeek). Most code was LLM-generated. 
> 
> **I assume no responsibility for the use, misuse, or consequences of this software.**
> 
> This is an **unofficial, third-party tool**. Users must have their own valid SurfShark subscription and WireGuard credentials.

---