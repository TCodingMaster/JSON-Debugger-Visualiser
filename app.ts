// Slovenski komentarji: jedrni tipi in strukture (brez sumnikov)
// JsonPrimitive: osnovne (primitivne) vrednosti JSON-a
type JsonPrimitive = string | number | boolean | null;
// JsonValue: lahko je primitiv, objekt ali polje
type JsonValue = JsonPrimitive | JsonObject | JsonArray;
// JsonObject: slovar kljuc -> vrednost
type JsonObject = { [key: string]: JsonValue };
// JsonArray: seznam vrednosti
type JsonArray = JsonValue[];

// Vrste vozlisc za izris v drevesu
type NodeKind = 'object' | 'array' | 'primitive';

// Model enega vozlisca v drevesnem pogledu
interface TreeNode {
	kind: NodeKind;
	key: string | null; // null only for the root value
	value: JsonValue;
	parent: TreeNode | null;
	open: boolean;
}

// Dostop do elementov DOM (glavni kontrolniki)
const dom = {
	parseBtn: document.getElementById('parseBtn') as HTMLButtonElement,
	expandAllBtn: document.getElementById('expandAllBtn') as HTMLButtonElement,
	collapseAllBtn: document.getElementById('collapseAllBtn') as HTMLButtonElement,
	jsonInput: document.getElementById('jsonInput') as HTMLTextAreaElement,
	inputError: document.getElementById('inputError') as HTMLDivElement,
	treeRoot: document.getElementById('treeRoot') as HTMLDivElement,
	themeToggle: document.getElementById('themeToggle') as HTMLButtonElement,
	exportBtn: document.getElementById('exportBtn') as HTMLButtonElement,
	langSelect: document.getElementById('langSelect') as HTMLSelectElement,
	titleText: document.getElementById('titleText') as HTMLHeadingElement,
	langLabel: document.getElementById('langLabel') as HTMLLabelElement,
};

let rootNode: TreeNode | null = null;
let forceOpenState: boolean | null = null; // controls expand/collapse all during next render

// I18n: nabor kljucev in besedila za jezike (EN, SL)
type I18nKeys =
	| 'title' | 'languageLabel' | 'toggleTheme' | 'export' | 'parseJson' | 'expandAll' | 'collapseAll' | 'placeholder'
	| 'root' | 'badgeObject' | 'badgeArray' | 'addPair' | 'addItem' | 'remove' | 'emptyObject' | 'emptyArray'
	| 'keyEmpty' | 'keyDuplicate' | 'invalidJson';

const i18n: Record<'en' | 'sl', Record<I18nKeys, string>> = {
	en: {
		title: 'JSON Debugger & Visualizer',
		languageLabel: 'Language',
		toggleTheme: 'Toggle Theme',
		export: 'Export',
		parseJson: 'Parse JSON',
		expandAll: 'Expand All',
		collapseAll: 'Collapse All',
		placeholder: 'Paste JSON here...',
		root: '(root)',
		badgeObject: '{ } object',
		badgeArray: '[ ] array',
		addPair: '+ pair',
		addItem: '+ item',
		remove: 'remove',
		emptyObject: 'Empty object',
		emptyArray: 'Empty array',
		keyEmpty: 'Key cannot be empty',
		keyDuplicate: 'Duplicate key in the same object',
		invalidJson: 'Invalid JSON',
	},
	sl: {
		title: 'JSON Razhroščevalnik in Vizualizator',
		languageLabel: 'Jezik',
		toggleTheme: 'Preklopi temo',
		export: 'Izvozi',
		parseJson: 'Razčleni JSON',
		expandAll: 'Razširi vse',
		collapseAll: 'Strni vse',
		placeholder: 'Prilepi JSON sem...',
		root: '(koren)',
		badgeObject: '{ } objekt',
		badgeArray: '[ ] polje',
		addPair: '+ par',
		addItem: '+ element',
		remove: 'odstrani',
		emptyObject: 'Prazen objekt',
		emptyArray: 'Prazno polje',
		keyEmpty: 'Ključ ne sme biti prazen',
		keyDuplicate: 'Podvojen ključ v istem objektu',
		invalidJson: 'Neveljaven JSON',
	},
};

let currentLang: 'en' | 'sl' = 'sl';

// t(key): vrne prevedeno besedilo za trenutni jezik
function t(key: I18nKeys): string {
	return i18n[currentLang][key];
}

// buildTree: zgradi vozlisce (brez rekurzije otrok); otroci se generirajo pri renderju
function buildTree(value: JsonValue, key: string | null = null, parent: TreeNode | null = null): TreeNode {
	const kind: NodeKind = Array.isArray(value) ? 'array' : (value !== null && typeof value === 'object' ? 'object' : 'primitive');
	return { kind, key, value, parent, open: true };
}

// setOpenRecursively: pripomocek (trenutno neuporabljen globalno), za masovno odpiranje/zapiranje
function setOpenRecursively(node: TreeNode, open: boolean): void {
	node.open = open;
	if (node.kind === 'object') {
		const obj = node.value as JsonObject;
		for (const k of Object.keys(obj)) setOpenRecursively(buildTree(obj[k], k, node), open);
	}
	if (node.kind === 'array') {
		const arr = node.value as JsonArray;
		for (let i = 0; i < arr.length; i++) setOpenRecursively(buildTree(arr[i], String(i), node), open);
	}
}

// Preverjanje veljavnosti kljucev z lokaliziranimi sporocili
function isValidKey(key: string, siblingKeys: string[]): { ok: boolean; reason?: string } {
    if (key.trim().length === 0) return { ok: false, reason: t('keyEmpty') };
    const duplicates = siblingKeys.filter(k => k === key).length;
    if (duplicates > 1) return { ok: false, reason: t('keyDuplicate') };
    return { ok: true };
}

// stringifyValue: pravilno izpise primitiv (npr. niz z narekovaji)
function stringifyValue(val: JsonValue): string {
	if (typeof val === 'string') return JSON.stringify(val);
	return String(val);
}

// parseEditedPrimitive: pretvori urejeno besedilo v primitiv (stevilka, boolean, null ali niz)
function parseEditedPrimitive(text: string): JsonPrimitive | undefined {
	const trimmed = text.trim();
	if (trimmed === 'null') return null;
	if (trimmed === 'true') return true;
	if (trimmed === 'false') return false;
	// number?
	if (/^[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$/.test(trimmed)) return Number(trimmed);
	// string (allow quotes or raw, convert to string)
	try {
		if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
			return JSON.parse(trimmed.replace(/'/g, '"')) as string;
		}
	} catch {}
	return trimmed; // treat as string
}

// render: pocisti in ponovno izrise celotno drevo
function render(root: TreeNode, mount: HTMLElement): void {
	mount.innerHTML = '';
	mount.appendChild(renderNode(root));
}

// renderNode: izrise eno vozlisce (vrstico) in po potrebi rekurzivno otroke
function renderNode(node: TreeNode): HTMLElement {
	const el = document.createElement('div');
	if (forceOpenState !== null) node.open = forceOpenState;
	el.className = 'json-node' + (node.open ? ' open' : '');

	const row = document.createElement('div');
	row.className = 'json-row';

	// twisty for non-primitives
	if (node.kind !== 'primitive') {
		const twist = document.createElement('div');
		twist.className = 'twist';
		twist.textContent = node.open ? '▾' : '▸';
		twist.addEventListener('click', () => {
			forceOpenState = null; // manual toggle cancels global force
			node.open = !node.open;
			twist.textContent = node.open ? '▾' : '▸';
			el.classList.toggle('open', node.open);
		});
		row.appendChild(twist);
	} else {
		const spacer = document.createElement('div');
		spacer.style.width = '16px';
		row.appendChild(spacer);
	}

	// kljuc (urejljiv, razen pri korenu)
	const keyEl = document.createElement('span');
	keyEl.className = 'key editable';
	if (node.key === null) {
		keyEl.textContent = t('root');
		keyEl.classList.add('pair');
		keyEl.contentEditable = 'false';
	} else {
		keyEl.textContent = node.key;
		keyEl.contentEditable = 'true';
		keyEl.addEventListener('blur', () => {
			const newKey = keyEl.textContent || '';
			if (!node.parent || node.parent.kind !== 'object') return; // arrays ignore keys
			const parentObj = node.parent.value as JsonObject;
			const siblingKeys = Object.keys(parentObj).map(k => (k === node.key ? newKey : k));
			const valid = isValidKey(newKey, siblingKeys);
			if (!valid.ok) {
				keyEl.classList.add('error');
				keyEl.title = valid.reason || '';
				keyEl.textContent = node.key || '';
				return;
			}
			if (newKey !== node.key) {
				// move property
				const oldKey = node.key as string;
				const valueCopy = (parentObj as any)[oldKey] as JsonValue;
				delete (parentObj as any)[oldKey];
				(parentObj as any)[newKey] = valueCopy;
				node.key = newKey;
			}
			keyEl.classList.remove('error');
			keyEl.title = '';
		});
	}
	row.appendChild(keyEl);

	const sep = document.createElement('span');
	sep.className = 'kv-sep';
	sep.textContent = node.key !== null ? ':' : '';
	row.appendChild(sep);

	// vrednost: prikaz in urejanje (le za primitive)
	const valueEl = document.createElement('span');
	valueEl.className = 'value editable';
	if (node.kind === 'primitive') {
		valueEl.textContent = stringifyValue(node.value);
		valueEl.contentEditable = 'true';
		valueEl.addEventListener('blur', () => {
			const next = parseEditedPrimitive(valueEl.textContent || '');
			if (next === undefined) {
				valueEl.classList.add('error');
				return;
			}
			valueEl.classList.remove('error');
			node.value = next;
			// also update in parent model
			if (node.parent) {
				if (node.parent.kind === 'array') {
					const idx = Number(node.key);
					(node.parent.value as JsonArray)[idx] = next;
				} else if (node.parent.kind === 'object') {
					const k = node.key as string;
					(node.parent.value as JsonObject)[k] = next;
				}
			}
			valueEl.textContent = stringifyValue(next);
		});
		row.appendChild(valueEl);
	} else {
		const badge = document.createElement('span');
		badge.className = 'badge';
		badge.textContent = node.kind === 'object' ? t('badgeObject') : t('badgeArray');
		row.appendChild(badge);
	}

	// inline controls (add/remove for objects/arrays)
	const controls = document.createElement('span');
	controls.className = 'controls-inline';
	if (node.kind === 'object') {
		const addBtn = document.createElement('button');
		addBtn.textContent = t('addPair');
		addBtn.addEventListener('click', () => {
			const obj = node.value as JsonObject;
			let base = 'key';
			let i = 1;
			while (Object.prototype.hasOwnProperty.call(obj, base + i)) i++;
			(obj as any)[base + i] = '';
			render(rootNode as TreeNode, dom.treeRoot);
		});
		controls.appendChild(addBtn);
	}
	if (node.kind === 'array') {
		const addBtn = document.createElement('button');
		addBtn.textContent = t('addItem');
		addBtn.addEventListener('click', () => {
			(node.value as JsonArray).push(null);
			render(rootNode as TreeNode, dom.treeRoot);
		});
		controls.appendChild(addBtn);
	}
	if (node.parent !== null) {
		const delBtn = document.createElement('button');
		delBtn.textContent = t('remove');
		delBtn.addEventListener('click', () => {
			if (!node.parent) return;
			if (node.parent.kind === 'array') {
				const idx = Number(node.key);
				(node.parent.value as JsonArray).splice(idx, 1);
			} else if (node.parent.kind === 'object') {
				delete (node.parent.value as JsonObject)[node.key as string];
			}
			render(rootNode as TreeNode, dom.treeRoot);
		});
		controls.appendChild(delBtn);
	}
	row.appendChild(controls);

	el.appendChild(row);

	if (node.kind !== 'primitive') {
		const childrenEl = document.createElement('div');
		childrenEl.className = 'json-children';
		if (node.kind === 'object') {
			const obj = node.value as JsonObject;
			const keys = Object.keys(obj);
			for (const k of keys) {
				const child = buildTree(obj[k], k, node);
				childrenEl.appendChild(renderNode(child));
			}
			if (keys.length === 0) {
				const hint = document.createElement('div');
				hint.className = 'hint';
				hint.textContent = t('emptyObject');
				childrenEl.appendChild(hint);
			}
		}
		if (node.kind === 'array') {
			const arr = node.value as JsonArray;
			for (let i = 0; i < arr.length; i++) {
				const child = buildTree(arr[i], String(i), node);
				childrenEl.appendChild(renderNode(child));
			}
			if (arr.length === 0) {
				const hint = document.createElement('div');
				hint.className = 'hint';
				hint.textContent = t('emptyArray');
				childrenEl.appendChild(hint);
			}
		}
		el.appendChild(childrenEl);
	}

	return el;
}

// parseFromTextarea: razcleni JSON iz levega urejevalnika in izrise drevo
function parseFromTextarea(): void {
	dom.inputError.textContent = '';
	try {
		const text = dom.jsonInput.value.trim();
		if (!text) {
			rootNode = buildTree({} as JsonObject);
			render(rootNode, dom.treeRoot);
			return;
		}
        const parsed = JSON.parse(text) as JsonValue;
		rootNode = buildTree(parsed);
		render(rootNode, dom.treeRoot);
	} catch (err: unknown) {
        dom.inputError.textContent = (err as Error)?.message || t('invalidJson');
	}
}

// expandAll / collapseAll: globalno razsiri/strne vozlisca
function expandAll(): void {
	if (!rootNode) return;
	forceOpenState = true;
	render(rootNode, dom.treeRoot);
}

function collapseAll(): void {
	if (!rootNode) return;
	forceOpenState = false;
	render(rootNode, dom.treeRoot);
}

// toggleTheme: preklop svetla/temna tema
function toggleTheme(): void {
	const current = document.body.getAttribute('data-theme') || 'light';
	const next = current === 'light' ? 'dark' : 'light';
	document.body.setAttribute('data-theme', next);
}

// exportJson: shrani trenutno strukturo kot .json datoteko
function exportJson(): void {
	if (!rootNode) return;
	const blob = new Blob([JSON.stringify(rootNode.value, null, 2)], { type: 'application/json' });
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = 'data.json';
	document.body.appendChild(a);
	a.click();
	a.remove();
	URL.revokeObjectURL(url);
}

// applyLanguageToUI: posodobi vsa besedila v UI glede na izbran jezik
function applyLanguageToUI(): void {
	dom.titleText.textContent = t('title');
	dom.langLabel.textContent = t('languageLabel');
	dom.themeToggle.textContent = t('toggleTheme');
	dom.exportBtn.textContent = t('export');
	dom.parseBtn.textContent = t('parseJson');
	dom.expandAllBtn.textContent = t('expandAll');
	dom.collapseAllBtn.textContent = t('collapseAll');
	dom.jsonInput.placeholder = t('placeholder');
}

// init: priklop dogodkov in zacetni izris
function init(): void {
	dom.parseBtn.addEventListener('click', parseFromTextarea);
	dom.expandAllBtn.addEventListener('click', expandAll);
	dom.collapseAllBtn.addEventListener('click', collapseAll);
	dom.themeToggle.addEventListener('click', toggleTheme);
	dom.exportBtn.addEventListener('click', exportJson);
    dom.langSelect.addEventListener('change', () => {
        const value = dom.langSelect.value === 'sl' ? 'sl' : 'en';
        currentLang = value;
        applyLanguageToUI();
        if (rootNode) render(rootNode, dom.treeRoot);
    });
	// load with empty object
	rootNode = buildTree({});
    applyLanguageToUI();
    render(rootNode, dom.treeRoot);
}

// Workaround for TS compile to JS; in browser we use app.js
document.addEventListener('DOMContentLoaded', init);

function applyLanguageToUI(): void {
    dom.titleText.textContent = t('title');
    dom.langLabel.textContent = t('languageLabel');
    dom.themeToggle.textContent = t('toggleTheme');
    dom.exportBtn.textContent = t('export');
    dom.parseBtn.textContent = t('parseJson');
    dom.expandAllBtn.textContent = t('expandAll');
    dom.collapseAllBtn.textContent = t('collapseAll');
    dom.jsonInput.placeholder = t('placeholder');
}


