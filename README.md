# JSON-Debugger-Visualiser
A lightweight **web-based JSON Debugger &amp; Visualizer** built with **TypeScript, HTML, and CSS** — no frameworks, no dependencies.   Paste your JSON, explore it as an **expandable tree**, **edit values inline**, and **export** your changes — all right in the browser.
![App Screenshot](https://user-images.githubusercontent.com/yourusername/demo-screenshot.pn)  
*(Add a real screenshot of your app once deployed!)*

---

## 🌟 Features

- 🧠 **Paste JSON → Visual Tree:** Instantly parse and visualize JSON structures in an expandable tree view.  
- ✏️ **Inline Editing:** Edit keys or values directly in the tree, with real-time validation.  
- ⚠️ **Error Detection:** Highlights invalid JSON syntax and duplicate or empty keys.  
- 🌓 **Light/Dark Theme Toggle:** Built-in theme switcher for comfortable viewing.  
- 🌍 **Multi-language Support:** English and Slovenian (easily extendable).  
- 💾 **Export to `.json`:** Save your modified JSON back to disk.  
- 🧱 **Zero Dependencies:** 100% client-side, no frameworks or build tools required.

---

## 🧰 Tech Stack

| Area | Technology |
|------|-------------|
| **Language** | TypeScript |
| **UI** | HTML + CSS (Flexbox + Grid + CSS variables) |
| **Logic** | Recursive DOM rendering |
| **Animations** | Pure CSS transitions for node expand/collapse |
| **Build** | Simple TypeScript compilation → `app.js` |

---

## 🚀 Live Demo

👉 *(Add your GitHub Pages or Netlify link here once you deploy it)*  
Example:  
**[Try it online](https://yourusername.github.io/json-debugger/)**

---

## 🧩 How It Works

1. Enter or paste your JSON into the left-side editor.  
2. Click **“Parse JSON”** to render it as a collapsible tree.  
3. Expand or collapse objects and arrays to navigate deeply nested data.  
4. Edit keys or values directly in place.  
   - Empty or duplicate keys show a warning.  
   - Edited primitives are automatically type-parsed (string, number, boolean, null).  
5. Toggle between **light** and **dark** themes.  
6. Click **Export** to download the modified JSON file.

---

## 🗂️ Project Structure

/
├── index.html # Main HTML entry file
├── styles.css # App styling (themes, layout, animations)
├── app.ts # Main TypeScript source
├── app.js # Compiled JavaScript output
└── LICENSE # MIT License file

yaml
Copy code

---

## 🛠️ Development

You can run this project locally with just a browser and TypeScript compiler.

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/json-debugger.git
cd json-debugger
2. Compile TypeScript (if you modify it)
bash
Copy code
tsc app.ts --target ES6 --outFile app.js
3. Open in your browser
Simply open index.html in your browser — no server needed.
```

## 🧑‍💻 Example
Paste this JSON into the editor to test:
```
json
Copy code
{
  "user": {
    "name": "Lina",
    "age": 24,
    "skills": ["TypeScript", "CSS", "JSON"],
    "active": true
  }
}

You’ll see a nested tree that can be expanded, edited, or exported.
```

## ⚙️ Roadmap / Future Ideas
  Search bar for keys/values

  Syntax highlighting for raw JSON input

  Keyboard shortcuts (Expand All / Collapse All)

  Drag-and-drop JSON file input

  Optional autosave to localStorage

## 🪪 License
 This project is licensed under the MIT License — feel free to use, modify, and share it.
 © 2025 [Your Name or GitHub Username]

## 🙌 Acknowledgments
  Built in pure TypeScript.

 Inspired by developer tools like VSCode’s JSON viewer and online JSON explorers.

 Localization: English 🇬🇧 and Slovenian 🇸🇮.

## 💡 Author
[Tin Lipovsek / TCodingMaster]
📂 https://github.com/TCodingMaster
https://instagram.com/tinkoo_08/





---

### Would you like me to:  
 - ✨ include your **name or GitHub username** automatically in the license + README placeholders,  
 and  - 📦 generate a `.zip` with the full README + LICENSE ready to upload to your repo?












