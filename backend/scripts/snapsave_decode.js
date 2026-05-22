// snapsave_decode.js — execute in node, capture html argument passed to $('...').html(...)
const https = require("https");
const querystring = require("querystring");
const TARGET_URL = process.argv[2];

function post(urlStr, body, headers) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr);
    const req = https.request({
      method: "POST", hostname: u.hostname, path: u.pathname + u.search,
      headers: { "Content-Length": Buffer.byteLength(body), ...headers },
    }, (res) => {
      let data = ""; res.on("data", c => data += c); res.on("end", () => resolve({ status: res.statusCode, body: data }));
    });
    req.on("error", reject);
    req.write(body); req.end();
  });
}

(async () => {
  const body = querystring.stringify({ url: TARGET_URL, lang: "en" });
  const r = await post("https://snapsave.app/action.php?lang=en", body, {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://snapsave.app",
    "Referer": "https://snapsave.app/en",
  });

  // The body is "var _0x...; var _0x... = function(...){...}; eval(_0xfn(p, a, c, k, e, d))"
  // We replace the outer eval with a capture function that gives us the unpacked string.
  let unpacked = "";
  const capturedEval = (s) => { unpacked += s + "\n\n---NEXT---\n\n"; };

  let captured = "";
  const fakeJq = (sel) => {
    const ret = {
      html: (s) => { if (typeof s === "string") captured += s; return ret; },
      append: (s) => { if (typeof s === "string") captured += s; return ret; },
      text: () => ret, val: () => "", show: () => ret, hide: () => ret,
      addClass: () => ret, removeClass: () => ret, attr: () => ret,
      css: () => ret, each: () => ret, find: () => ret, ready: (f) => { try { f(); } catch (e) {} },
    };
    return ret;
  };
  const fakeEl = {
    set innerHTML(v) { captured += String(v); },
    get innerHTML() { return ""; },
    style: {}, classList: { add: () => {}, remove: () => {} },
  };

  // Override eval & document & jQuery globals.
  const sandboxed = `
    var eval = arguments[0];
    var $ = arguments[1];
    var jQuery = arguments[1];
    var fakeEl = arguments[2];
    var window = {
      location: { hostname: "snapsave.app", href: "https://snapsave.app/en" },
      document: { getElementById: function() { return fakeEl; }, querySelector: function() { return fakeEl; } }
    };
    var document = window.document;
    var navigator = { userAgent: "Mozilla/5.0" };
    ${r.body}
  `;

  try {
    const fn = new Function("eval", "$", "fakeEl", sandboxed);
    fn(capturedEval, fakeJq, fakeEl);
  } catch (e) {
    // Some packers run jQuery handlers — non-fatal.
  }

  // Now actually run the unpacked code(s) in a sandbox where document/window are mocked.
  for (const piece of unpacked.split("---NEXT---")) {
    if (!piece.trim()) continue;
    const inner = `
      var fakeEl = arguments[0];
      var window = {
        location: { hostname: "snapsave.app", href: "https://snapsave.app/en" },
        document: { getElementById: function() { return fakeEl; }, querySelector: function() { return fakeEl; } }
      };
      var document = window.document;
      try { ${piece} } catch(e) {}
    `;
    try {
      const fn2 = new Function("fakeEl", inner);
      fn2(fakeEl);
    } catch (e) {}
  }

  // The unpacked code itself contains $('...').html('...') — extract the html arg.
  const htmlMatches = [...unpacked.matchAll(/\$\("[^"]+"\)\.html\("((?:\\.|[^"\\])*)"\)/g)];
  for (const m of htmlMatches) {
    captured += m[1].replace(/\\\//g, "/").replace(/\\"/g, '"').replace(/\\n/g, "\n");
  }

  // Extract video URLs
  const urlsRaw = [...captured.matchAll(/https?:\/\/[^\s"'<>]+\.(?:mp4|webp|jpg|jpeg)[^\s"'<>]*/g)].map(s => s[0]);
  const allMatches = [...captured.matchAll(/href="(https?:\/\/[^"]+)"/g)].map(m => m[1]);
  const titleMatch = captured.match(/<h3[^>]*>([^<]+)<\/h3>/);
  const tableRows = [...captured.matchAll(/<tr>[\s\S]*?<\/tr>/g)].map(m => m[0]);

  console.log(JSON.stringify({
    title: titleMatch ? titleMatch[1].trim() : null,
    media_urls: [...new Set(urlsRaw)],
    href_urls: [...new Set(allMatches)].filter(u => !u.includes("snapsave")),
    raw_len: captured.length,
    unpacked_len: unpacked.length,
  }, null, 2));
})();
