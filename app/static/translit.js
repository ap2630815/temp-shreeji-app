/* English -> Gujarati for the forms that have both (farmer_name + farmer_name_gu, village_name + village_name_gu, name + name_gu ...).
   Built in and offline: nothing is sent anywhere. When an English box changes, its Gujarati twin is filled from it (the Gujarati stays editable;
   it is replaced again the next time the English changes).
   Names are written the way they sound ("Karsanbhai" -> કરસનભાઈ); common words (grains, surnames, villages) come from the word list below;
   everything else goes through the sound rules. Add a word to GU_WORDS to fix or force a spelling (lower case key). */
(function () {
  'use strict';

  // ---- word list: whole words, lower case -> Gujarati. Grains and common things are translated, surnames and places spelled.
  var GU_WORDS = {
    // grains and produce
    wheat: 'ઘઉં', cotton: 'કપાસ', groundnut: 'મગફળી', peanut: 'મગફળી', castor: 'એરંડા', cumin: 'જીરું', jeera: 'જીરું', sesame: 'તલ', gram: 'ચણા', chana: 'ચણા',
    bajra: 'બાજરી', jowar: 'જુવાર', maize: 'મકાઈ', corn: 'મકાઈ', tuver: 'તુવેર', toor: 'તુવેર', tur: 'તુવેર', moong: 'મગ', mung: 'મગ', urad: 'અડદ', soybean: 'સોયાબીન',
    mustard: 'રાઈ', coriander: 'ધાણા', dhana: 'ધાણા', fennel: 'વરિયાળી', rice: 'ચોખા', paddy: 'ડાંગર', onion: 'ડુંગળી', garlic: 'લસણ', chilli: 'મરચાં', turmeric: 'હળદર',
    isabgul: 'ઇસબગુલ', guar: 'ગુવાર', sugarcane: 'શેરડી', jaggery: 'ગોળ', millet: 'બાજરી', barley: 'જવ', lentil: 'મસૂર', masoor: 'મસૂર', rajma: 'રાજમા', peas: 'વટાણા',
    // titles and common name endings
    shri: 'શ્રી', smt: 'શ્રીમતી', kumari: 'કુમારી', 'mr.': 'શ્રી', mr: 'શ્રી', mrs: 'શ્રીમતી', self: 'સ્વયં',
    // surnames
    patel: 'પટેલ', shah: 'શાહ', mehta: 'મહેતા', desai: 'દેસાઈ', joshi: 'જોષી', parmar: 'પરમાર', solanki: 'સોલંકી', thakkar: 'ઠક્કર', thakar: 'ઠાકર', rathod: 'રાઠોડ',
    vaghela: 'વાઘેલા', chauhan: 'ચૌહાણ', chavda: 'ચાવડા', jadeja: 'જાડેજા', gohil: 'ગોહિલ', ahir: 'આહીર', rabari: 'રબારી', bharwad: 'ભરવાડ', kumbhani: 'કુંભાણી',
    sheth: 'શેઠ', gandhi: 'ગાંધી', trivedi: 'ત્રિવેદી', pandya: 'પંડ્યા', dave: 'દવે', bhatt: 'ભટ્ટ', raval: 'રાવલ', modi: 'મોદી', kotak: 'કોટક', vyas: 'વ્યાસ',
    zala: 'ઝાલા', sarvaiya: 'સરવૈયા', dodiya: 'દોડિયા', makwana: 'મકવાણા', baria: 'બારિયા', rajput: 'રાજપૂત', vasoya: 'વસોયા', sorathiya: 'સોરઠિયા', kathiriya: 'કથીરિયા',
    vaghasiya: 'વાઘાસિયા', ladani: 'લાડાણી', faldu: 'ફળદુ', kakadiya: 'કાકડિયા', dobariya: 'દોબરિયા', ghetiya: 'ઘેટિયા', gajera: 'ગજેરા', sakariya: 'સાકરિયા',
    // first names
    ramesh: 'રમેશ', suresh: 'સુરેશ', dinesh: 'દિનેશ', mahesh: 'મહેશ', hasmukh: 'હસમુખ', kantilal: 'કાંતિલાલ', bipin: 'બિપિન', prakash: 'પ્રકાશ', jayesh: 'જયેશ', nilesh: 'નિલેશ',
    rajesh: 'રાજેશ', mukesh: 'મુકેશ', ashok: 'અશોક', amit: 'અમિત', anil: 'અનિલ', kishor: 'કિશોર', jagdish: 'જગદીશ', ishwar: 'ઈશ્વર', bhagwan: 'ભગવાન', krishna: 'કૃષ્ણ',
    // places
    rajkot: 'રાજકોટ', junagadh: 'જૂનાગઢ', amreli: 'અમરેલી', bhavnagar: 'ભાવનગર', surat: 'સુરત', ahmedabad: 'અમદાવાદ', vadodara: 'વડોદરા', gondal: 'ગોંડલ', jetpur: 'જેતપુર',
    upleta: 'ઉપલેટા', dhoraji: 'ધોરાજી', morbi: 'મોરબી', jamnagar: 'જામનગર', porbandar: 'પોરબંદર', keshod: 'કેશોદ', visavadar: 'વિસાવદર', una: 'ઊના', botad: 'બોટાદ',
    gadhada: 'ગઢડા', jasdan: 'જસદણ', wankaner: 'વાંકાનેર', sayla: 'સાયલા', limbdi: 'લીંબડી', dhrangadhra: 'ધ્રાંગધ્રા', halvad: 'હળવદ', mahuva: 'મહુવા', talaja: 'તળાજા',
    // shop words
    traders: 'ટ્રેડર્સ', trading: 'ટ્રેડિંગ', agro: 'એગ્રો', industries: 'ઇન્ડસ્ટ્રીઝ', oil: 'ઓઇલ', mill: 'મિલ', mills: 'મિલ્સ', foods: 'ફૂડ્સ', enterprise: 'એન્ટરપ્રાઇઝ',
    enterprises: 'એન્ટરપ્રાઇઝ', and: 'અને', co: 'કો', company: 'કંપની', ltd: 'લિ.', pvt: 'પ્રા.', bags: 'બેગ', group: 'જૂથ', labour: 'મજૂર', transport: 'ટ્રાન્સપોર્ટ'
  };

  // ---- endings written as one piece when they close a word
  var SUFFIX = { ji: 'જી', bhai: 'ભાઈ', ben: 'બેન', kumar: 'કુમાર', lal: 'લાલ', chandra: 'ચંદ્ર', singh: 'સિંહ', raj: 'રાજ', dass: 'દાસ', das: 'દાસ', prasad: 'પ્રસાદ', shankar: 'શંકર' };

  // ---- sounds
  var CONS = {
    ksh: 'ક્ષ', gny: 'જ્ઞ', shr: 'શ્ર', chh: 'છ', 'kh': 'ખ', 'gh': 'ઘ', 'ch': 'ચ', 'jh': 'ઝ', 'th': 'થ', 'dh': 'ધ', 'ph': 'ફ', 'bh': 'ભ', 'sh': 'શ', 'Th': 'ઠ', 'Dh': 'ઢ',
    k: 'ક', g: 'ગ', c: 'ક', j: 'જ', t: 'ત', d: 'દ', T: 'ટ', D: 'ડ', n: 'ન', N: 'ણ', p: 'પ', f: 'ફ', b: 'બ', m: 'મ', y: 'ય', r: 'ર', l: 'લ', L: 'ળ', v: 'વ', w: 'વ',
    s: 'સ', h: 'હ', z: 'ઝ', q: 'ક', x: 'ક્સ'
  };
  var CONS_KEYS = ['ksh', 'gny', 'shr', 'chh', 'kh', 'gh', 'ch', 'jh', 'th', 'dh', 'ph', 'bh', 'sh', 'Th', 'Dh'];
  var INDEP = { a: 'અ', aa: 'આ', i: 'ઇ', ee: 'ઈ', ii: 'ઈ', u: 'ઉ', oo: 'ઊ', uu: 'ઊ', e: 'એ', ai: 'ઐ', o: 'ઓ', au: 'ઔ' };
  var MATRA = { a: '', aa: 'ા', i: 'િ', ee: 'ી', ii: 'ી', u: 'ુ', oo: 'ૂ', uu: 'ૂ', e: 'ે', ai: 'ૈ', o: 'ો', au: 'ૌ' };
  var VOWEL_KEYS = ['aa', 'ai', 'au', 'ee', 'ii', 'oo', 'uu', 'a', 'e', 'i', 'o', 'u'];
  var HALANT = '્';
  var VIRAMA_FIRST = { k: 1, g: 1, c: 1, j: 1, t: 1, d: 1, p: 1, b: 1, s: 1, f: 1, kh: 1, gh: 1, th: 1, dh: 1, ph: 1, bh: 1, sh: 1, shr: 0, ch: 1, z: 1, v: 0, w: 0, m: 0, n: 0, r: 0, l: 0, y: 0, h: 0 };
  var VIRAMA_SECOND_LETTERS = 'rylvw';   // pr, kr, ty, sw, pl ...
  var SPECIAL_PAIRS = { st: 1, sth: 1, sk: 1, sp: 1, sm: 1, sn: 1, ndr: 1, ngr: 1 };   // sound clusters that join (સ્ત, સ્થ ...)
  var ANUSVARA_BEFORE = 'kgcjtdTDpb';   // n / m before these letters is written as ં

  function isLetter(ch) { return /[A-Za-z]/.test(ch); }
  function isVowelLetter(ch) { return 'aeiouAEIOU'.indexOf(ch) > -1; }

  function readConsonant(w, i) {
    for (var k = 0; k < CONS_KEYS.length; k++) {
      var key = CONS_KEYS[k], seg = w.substr(i, key.length);
      if (key === 'Th' || key === 'Dh') { if (seg === key) return key; }
      else if (seg.length === key.length && seg.toLowerCase() === key) return key;
    }
    var c = w.charAt(i);
    if (CONS[c] !== undefined) return c;
    var low = c.toLowerCase();
    return CONS[low] !== undefined ? low : null;
  }

  function readVowel(w, i) {
    var s = w.substr(i, 2).toLowerCase();
    for (var k = 0; k < VOWEL_KEYS.length; k++) {
      var key = VOWEL_KEYS[k];
      if (s.substr(0, key.length) === key && w.substr(i, key.length).toLowerCase() === key) return key;
    }
    return null;
  }

  function soundWord(word, finalPiece) {
    // normalise: a capital letter inside the word marks a hard sound (T D N L); the first letter and any other capital are plain
    var w = word.charAt(0).toLowerCase() + word.slice(1);
    var chars = [];
    var i = 0, out = '', prevCons = false;
    var tokens = [];
    // tokenise into consonant / vowel / other
    while (i < w.length) {
      var ch = w.charAt(i);
      if (!isLetter(ch)) { tokens.push({ t: 'o', v: ch }); i++; continue; }
      var cons = readConsonant(w, i);
      var isHard = 'TDNL'.indexOf(ch) > -1 && i > 0;
      if (cons && !(isVowelLetter(ch)) ) {
        var key = cons;
        if (!isHard && key.length === 1 && 'TDNL'.indexOf(key) > -1) key = key.toLowerCase();   // a capital that is not a hard sound
        if (key.length === 2 && (key === 'Th' || key === 'Dh') && i === 0) key = key.toLowerCase();
        tokens.push({ t: 'c', k: key, raw: w.substr(i, cons.length).toLowerCase() });
        i += cons.length; continue;
      }
      var vow = readVowel(w, i);
      if (vow) { tokens.push({ t: 'v', k: vow }); i += vow.length; continue; }
      tokens.push({ t: 'o', v: ch }); i++;
    }
    // double letters (tt, ll, nn ...) join; 'ai' at the end of a word is "aa-ee"
    for (var p = 0; p < tokens.length; p++) {
      var tk = tokens[p], nx = tokens[p + 1];
      if (tk.t === 'v' && tk.k === 'ai' && p === tokens.length - 1 && p > 0 && tokens[p - 1].t === 'c') { tk.fix = 'ાઈ'; }
      if (tk.t === 'v' && tk.k === 'a' && p === tokens.length - 1 && p > 0 && tokens[p - 1].t === 'c' && tokens.length > 3) { tk.fix = 'ા'; }   // a closing "a" is long: Mehta, Gita
    }
    for (var q = 0; q < tokens.length; q++) {
      var t = tokens[q], n = tokens[q + 1], pr = tokens[q - 1];
      if (t.t === 'o') { out += t.v; prevCons = false; continue; }
      if (t.t === 'v' && pr && pr.t === 'v' && (pr.k === 'i' || pr.k === 'ee' || pr.k === 'ii')) {   // Zalavadia: the "i" and "a" are joined by a "y" sound
        out += 'ય' + (q === tokens.length - 1 && t.k === 'a' ? 'ા' : MATRA[t.k]);
        prevCons = false; continue;
      }
      if (t.t === 'v') {
        if (t.fix) { out += (prevCons ? t.fix : (t.fix === 'ાઈ' ? 'આઈ' : 'આ')); }
        else if (prevCons) out += MATRA[t.k];
        else out += INDEP[t.k];
        prevCons = false; continue;
      }
      // consonant
      var glyph = CONS[t.k];
      var next = n && n.t === 'c' ? n : null;
      // n / m before a hard-stop letter at the middle of a word is an anusvara: Gondal -> ગોંડલ
      if ((t.k === 'n' || t.k === 'm') && next && ANUSVARA_BEFORE.indexOf(next.raw.charAt(0)) > -1 && pr && pr.t === 'v') { out += 'ં'; prevCons = false; continue; }
      out += glyph;
      if (next) {
        var joins = false;
        var two = (t.raw + next.raw);
        if (t.raw === next.raw && t.raw.length === 1) joins = true;                                                    // tt, ll, nn
        else if (VIRAMA_FIRST[t.raw] && next.raw.length === 1 && VIRAMA_SECOND_LETTERS.indexOf(next.raw) > -1) joins = true;   // pr, kr, sw
        else if (SPECIAL_PAIRS[two]) joins = true;
        if (joins) out += HALANT;
      }
      prevCons = true;
    }
    return out;
  }

  function convertWord(word) {
    var low = word.toLowerCase();
    if (GU_WORDS[low] !== undefined) return GU_WORDS[low];
    // a closing piece (bhai, ben, kumar ...) after a longer stem
    if (SUFFIX[low] !== undefined) return SUFFIX[low];   // the word is one of the endings: Kumar, Lal, Singh
    var keys = Object.keys(SUFFIX);
    for (var k = 0; k < keys.length; k++) {
      var s = keys[k];
      if (low.length > s.length + 1 && low.slice(-s.length) === s) {
        var stem = word.slice(0, word.length - s.length);
        var lowStem = stem.toLowerCase();
        return (GU_WORDS[lowStem] !== undefined ? GU_WORDS[lowStem] : (SUFFIX[lowStem] !== undefined ? SUFFIX[lowStem] : soundWord(stem, true))) + SUFFIX[s];
      }
    }
    return soundWord(word, false);
  }

  function toGujarati(text) {
    if (!text) return '';
    return String(text).replace(/[A-Za-z][A-Za-z']*/g, function (w) { return convertWord(w.replace(/'/g, '')); });
  }

  // ---- wiring: an English box and its _gu twin in the same form (also the four name parts of a farmer: name__1 ... name__4)
  function twin(el) {
    var name = el.getAttribute('name') || '';
    var m = /^(.+?)(__\d)?$/.exec(name);
    if (!m || /_gu$/.test(m[1]) || !el.form) return null;
    var partner = el.form.elements[m[1] + '_gu' + (m[2] || '')];
    return partner && partner.tagName === 'INPUT' ? partner : null;
  }
  function isGujaratiTwin(el) { return /_gu(__\d)?$/.test(el.getAttribute('name') || ''); }
  // A Gujarati box you have typed in yourself is a correction and is kept: the English no longer overwrites it.
  // A Gujarati box that already holds something other than what the English would give (a correction saved earlier) counts the same.
  function follow(e) {
    var el = e.target;
    if (!el || el.tagName !== 'INPUT') return;
    if (isGujaratiTwin(el)) { el.setAttribute('data-gu-manual', el.value ? '1' : '0'); return; }   // you are editing the Gujarati
    var partner = twin(el);
    if (!partner || partner.disabled || partner.readOnly) return;
    if (!el.value.trim()) { partner.value = ''; partner.setAttribute('data-gu-manual', '0'); return; }   // English cleared: start again
    if (!partner.hasAttribute('data-gu-manual')) {
      partner.setAttribute('data-gu-manual', partner.value && partner.value !== toGujarati(el.defaultValue) ? '1' : '0');
    }
    if (partner.getAttribute('data-gu-manual') === '1') return;
    partner.value = toGujarati(el.value);
  }
  document.addEventListener('input', follow);
  document.addEventListener('change', function (e) { if (e.target && e.target.tagName === 'INPUT' && !isGujaratiTwin(e.target)) follow(e); });
  window.toGujarati = toGujarati;
})();
