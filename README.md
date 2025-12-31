# JSON-Debugger-Visualiser
A lightweight **web-based JSON Debugger &amp; Visualizer** built with **TypeScript, HTML, and CSS** — no frameworks, no dependencies.   Paste your JSON, explore it as an **expandable tree**, **edit values inline**, and **export** your changes — all right in the browser.
## App Screenshot Light mode 
<img width="1920" height="888" alt="Screenshot_20251029_224222" src="https://github.com/user-attachments/assets/0154d58c-6389-4737-84ef-2d680201c56d" />

## App Screenshot Dark mode 
<img width="1910" height="888" alt="Screenshot_20251029_224536" src="https://github.com/user-attachments/assets/9198464f-d76f-466d-a4da-6d62a0b90b2c" />
---

##  Features

-  **Paste JSON → Visual Tree:** Instantly parse and visualize JSON structures in an expandable tree view.  
-  **Inline Editing:** Edit keys or values directly in the tree, with real-time validation.  
-  **Error Detection:** Highlights invalid JSON syntax and duplicate or empty keys.  
-  **Light/Dark Theme Toggle:** Built-in theme switcher for comfortable viewing.  
-  **Multi-language Support:** English and Slovenian (easily extendable).  
-  **Export to `.json`:** Save your modified JSON back to disk.  
-  **Zero Dependencies:** 100% client-side, no frameworks or build tools required.

---

##  Tech Stack

| Area | Technology |
|------|-------------|
| **Language** | TypeScript |
| **UI** | HTML + CSS (Flexbox + Grid + CSS variables) |
| **Logic** | Recursive DOM rendering |
| **Animations** | Pure CSS transitions for node expand/collapse |
| **Build** | Simple TypeScript compilation → `app.js` |

---

##  Live Demo
 
**[Try it online](https://tcodingmaster.github.io/JSON-Debugger-Visualiser/)**

---

##  How It Works

1. Enter or paste your JSON into the left-side editor.  
2. Click **“Parse JSON”** to render it as a collapsible tree.  
3. Expand or collapse objects and arrays to navigate deeply nested data.  
4. Edit keys or values directly in place.  
   - Empty or duplicate keys show a warning.  
   - Edited primitives are automatically type-parsed (string, number, boolean, null).  
5. Toggle between **light** and **dark** themes.  
6. Click **Export** to download the modified JSON file.

---

##  Project Structure

/
├── index.html # Main HTML entry file
├── styles.css # App styling (themes, layout, animations)
├── app.ts # Main TypeScript source
├── app.js # Compiled JavaScript output
└── LICENSE # MIT License file

yaml
Copy code

---

##  Development

You can run this project locally with just a browser and TypeScript compiler or an IDE.

### 1. instructions to Clone the repository 
## MACOS 
``` bash
# Navigate to downloads
cd ~/Downloads
# Clone the repository
git clone https://github.com/TCodingMaster/JSON-Debugger-Visualiser.git
# Navigate into the directory
cd JSON-Debugger-Visualiser
# Pull latest changes (if already cloned)
git pull
# Open in Finder
open .
```
## Windows
``` shell
# Navigate to downloads
cd C:\Users\%USERNAME%\Downloads
# Clone the repository
git clone https://github.com/TCodingMaster/JSON-Debugger-Visualiser.git
# Navigate into the directory
cd JSON-Debugger-Visualiser
# Pull latest changes (if already cloned)
git pull
# Open in File Explorer
explorer .
```
## Linux
``` bash
# Navigate to downloads
cd ~/Downloads
# Clone the repository
git clone https://github.com/TCodingMaster/JSON-Debugger-Visualiser.git
# Navigate into the directory
cd JSON-Debugger-Visualiser
# Pull latest changes (if already cloned)
git pull
# Open in file manager (varies by desktop environment)
xdg-open .
# Or use: nautilus . (GNOME), dolphin . (KDE), thunar . (XFCE)
```

##  Example
Paste this JSON into the editor to test:
``` json
{
  "user": {
    "name": "Lina",
    "age": 24,
    "skills": ["TypeScript", "CSS", "JSON"],
    "active": true
  }
}
```

You can find errors when cloning to files and opening `index.html`. Only `index.html` is working not the typescript and Javascript file
**Consider using an IDE like: Visual studio, VS code, Cursor or Notepad++**


## License
 This project is licensed under the MIT License — feel free to use, modify, and share it.
 © 2025 [Your Name or GitHub Username]

## Acknowledgments
  Built in pure TypeScript.

 Inspired by developer tools like VSCode’s JSON viewer and online JSON explorers.

 Localization: English 🇬🇧 and Slovenian 🇸🇮.

##  Author
[Tin Lipovsek / TCodingMaster]
https://github.com/TCodingMaster
https://instagram.com/tinkoo_08/





---

### Would you like me to:  
 - include your **name or GitHub username** automatically in the license + README placeholders,  
 and  - generate a `.zip` with the full README + LICENSE ready to upload to your repo?












