import MarkdownIt from "markdown-it";
import hljs from "highlight.js/lib/core";

// Register only the languages we'll actually see in GitHub context
import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import python from "highlight.js/lib/languages/python";
import bash from "highlight.js/lib/languages/bash";
import json from "highlight.js/lib/languages/json";
import yaml from "highlight.js/lib/languages/yaml";
import xml from "highlight.js/lib/languages/xml";
import css from "highlight.js/lib/languages/css";
import markdown from "highlight.js/lib/languages/markdown";
import diff from "highlight.js/lib/languages/diff";

hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("js", javascript);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("ts", typescript);
hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("sh", bash);
hljs.registerLanguage("json", json);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("yml", yaml);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("html", xml);
hljs.registerLanguage("css", css);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("md", markdown);
hljs.registerLanguage("diff", diff);

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  highlight(str: string, lang: string): string {
    const escaped = md.utils.escapeHtml(str);
    let highlighted: string;

    if (lang && hljs.getLanguage(lang)) {
      try {
        highlighted = hljs.highlight(str, { language: lang }).value;
      } catch {
        highlighted = escaped;
      }
    } else {
      highlighted = escaped;
    }

    const langLabel = lang ? md.utils.escapeHtml(lang) : "";
    return (
      `<div class="code-block">` +
      `<div class="code-block-header">` +
      `<span class="code-lang">${langLabel}</span>` +
      `<button class="copy-btn" onclick="navigator.clipboard.writeText(this.closest('.code-block').querySelector('code').textContent)">Kopieren</button>` +
      `</div>` +
      `<pre><code class="hljs${lang ? ` language-${langLabel}` : ""}">${highlighted}</code></pre>` +
      `</div>`
    );
  },
});

export function useMarkdown() {
  function render(text: string): string {
    if (!text) return "";
    return md.render(text);
  }

  return { render };
}
