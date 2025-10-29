//  zbrane reference na DOM elemente
const dom = {
	parseBtn: document.getElementById('parseBtn'),
	expandAllBtn: document.getElementById('expandAllBtn'),
	collapseAllBtn: document.getElementById('collapseAllBtn'),
	jsonInput: document.getElementById('jsonInput'),
	inputError: document.getElementById('inputError'),
	treeRoot: document.getElementById('treeRoot'),
	themeToggle: document.getElementById('themeToggle'),
	exportBtn: document.getElementById('exportBtn'),
	langSelect: document.getElementById('langSelect'),
	titleText: document.getElementById('titleText'),
	langLabel: document.getElementById('langLabel'),
};

let rootNode = null;
let forceOpenState = null;
let currentLang = 'sl';

// i18n: besedila za angleščino in slovenščino
const i18n = {
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
	}
};

function t(key) {
	return i18n[currentLang][key];
}

function nodeKind(value) {
	return Array.isArray(value) ? 'array' : (value !== null && typeof value === 'object' ? 'object' : 'primitive');
}

// buildTree: pripravi vozlišče (otroci se izrišejo pri renderju)
function buildTree(value, key = null, parent = null) {
	return { kind: nodeKind(value), key, value, parent, open: true };
}

// Preverjanje ključev z lokaliziranimi sporočili
function isValidKey(key, siblingKeys) {
	if (key.trim().length === 0) return { ok: false, reason: t('keyEmpty') };
	const duplicates = siblingKeys.filter(k => k === key).length;
	if (duplicates > 1) return { ok: false, reason: t('keyDuplicate') };
	return { ok: true };
}

// stringifyValue: pravilno prikaže primitiven tip
function stringifyValue(val) {
	if (typeof val === 'string') return JSON.stringify(val);
	return String(val);
}

// parseEditedPrimitive: pretvori v number/boolean/null ali niz
function parseEditedPrimitive(text) {
	const trimmed = text.trim();
	if (trimmed === 'null') return null;
	if (trimmed === 'true') return true;
	if (trimmed === 'false') return false;
	if (/^[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$/.test(trimmed)) return Number(trimmed);
	try {
		if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
			return JSON.parse(trimmed.replace(/'/g, '"'));
		}
	} catch {}
	return trimmed;
}

// render: izriše celotno drevo v desni plošči
function render(root, mount) {
	mount.innerHTML = '';
	mount.appendChild(renderNode(root));
}

// renderNode: izriše eno vozlišče in morebitne otroke
function renderNode(node) {
	const el = document.createElement('div');
	if (forceOpenState !== null) node.open = forceOpenState;
	el.className = 'json-node' + (node.open ? ' open' : '');

	const row = document.createElement('div');
	row.className = 'json-row';

	if (node.kind !== 'primitive') {
		const twist = document.createElement('div');
		twist.className = 'twist';
		twist.textContent = node.open ? '▾' : '▸';
		twist.addEventListener('click', () => {
			forceOpenState = null;
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
			if (!node.parent || node.parent.kind !== 'object') return;
			const parentObj = node.parent.value;
			const siblingKeys = Object.keys(parentObj).map(k => (k === node.key ? newKey : k));
			const valid = isValidKey(newKey, siblingKeys);
			if (!valid.ok) {
				keyEl.classList.add('error');
				keyEl.title = valid.reason || '';
				keyEl.textContent = node.key || '';
				return;
			}
			if (newKey !== node.key) {
				const oldKey = node.key;
				const valueCopy = parentObj[oldKey];
				delete parentObj[oldKey];
				parentObj[newKey] = valueCopy;
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
			if (node.parent) {
				if (node.parent.kind === 'array') {
					const idx = Number(node.key);
					node.parent.value[idx] = next;
				} else if (node.parent.kind === 'object') {
					const k = node.key;
					node.parent.value[k] = next;
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

	const controls = document.createElement('span');
	controls.className = 'controls-inline';
	if (node.kind === 'object') {
		const addBtn = document.createElement('button');
		addBtn.textContent = t('addPair');
		addBtn.addEventListener('click', () => {
			const obj = node.value;
			let base = 'key';
			let i = 1;
			while (Object.prototype.hasOwnProperty.call(obj, base + i)) i++;
			obj[base + i] = '';
			render(rootNode, dom.treeRoot);
		});
		controls.appendChild(addBtn);
	}
	if (node.kind === 'array') {
		const addBtn = document.createElement('button');
		addBtn.textContent = t('addItem');
		addBtn.addEventListener('click', () => {
			node.value.push(null);
			render(rootNode, dom.treeRoot);
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
				node.parent.value.splice(idx, 1);
			} else if (node.parent.kind === 'object') {
				delete node.parent.value[node.key];
			}
			render(rootNode, dom.treeRoot);
		});
		controls.appendChild(delBtn);
	}
	row.appendChild(controls);

	el.appendChild(row);

	if (node.kind !== 'primitive') {
		const childrenEl = document.createElement('div');
		childrenEl.className = 'json-children';
		if (node.kind === 'object') {
			const obj = node.value;
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
			const arr = node.value;
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
function parseFromTextarea() {
	dom.inputError.textContent = '';
	try {
		const text = dom.jsonInput.value.trim();
		if (!text) {
			rootNode = buildTree({});
			render(rootNode, dom.treeRoot);
			return;
		}
		const parsed = JSON.parse(text);
		rootNode = buildTree(parsed);
		render(rootNode, dom.treeRoot);
	} catch (err) {
		dom.inputError.textContent = err?.message || t('invalidJson');
	}
}

// Razsiri vsa vozlisca
function expandAll() {
	if (!rootNode) return;
	forceOpenState = true;
	render(rootNode, dom.treeRoot);
}

// Strni vsa vozlisca
function collapseAll() {
	if (!rootNode) return;
	forceOpenState = false;
	render(rootNode, dom.treeRoot);
}

// Preklop teme: svetla/temna
function toggleTheme() {
	const current = document.body.getAttribute('data-theme') || 'light';
	const next = current === 'light' ? 'dark' : 'light';
	document.body.setAttribute('data-theme', next);
}

// Izvoz v .json datoteko
function exportJson() {
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

// Posodobi vsa besedila v uporabniskem vmesniku
function applyLanguageToUI() {
	dom.titleText.textContent = t('title');
	dom.langLabel.textContent = t('languageLabel');
	dom.themeToggle.textContent = t('toggleTheme');
	dom.exportBtn.textContent = t('export');
	dom.parseBtn.textContent = t('parseJson');
	dom.expandAllBtn.textContent = t('expandAll');
	dom.collapseAllBtn.textContent = t('collapseAll');
	dom.jsonInput.placeholder = t('placeholder');
}

// Inicializacija: dogodki in zacetni izris
function init() {
	dom.parseBtn?.addEventListener('click', parseFromTextarea);
	dom.expandAllBtn?.addEventListener('click', expandAll);
	dom.collapseAllBtn?.addEventListener('click', collapseAll);
	dom.themeToggle?.addEventListener('click', toggleTheme);
	dom.exportBtn?.addEventListener('click', exportJson);
	dom.langSelect?.addEventListener('change', () => {
		const value = dom.langSelect.value === 'sl' ? 'sl' : 'en';
		currentLang = value;
		applyLanguageToUI();
		if (rootNode) render(rootNode, dom.treeRoot);
	});
	rootNode = buildTree({});
	applyLanguageToUI();
	render(rootNode, dom.treeRoot);
}

document.addEventListener('DOMContentLoaded', init);


