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

function createRenderer(options: { typographer: boolean }): MarkdownIt {
  const md: MarkdownIt = new MarkdownIt({
    // Never pass raw HTML through — issue bodies are untrusted input
    html: false,
    linkify: true,
    typographer: options.typographer,
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

  // GitHub task lists ("- [ ] todo" / "- [x] done") → read-only checkboxes.
  // Common in issue bodies (acceptance criteria), which the chat renders.
  md.core.ruler.after("inline", "task_lists", (state) => {
    const tokens = state.tokens;
    for (let i = 2; i < tokens.length; i++) {
      const inline = tokens[i]!;
      if (
        inline.type !== "inline" ||
        tokens[i - 1]!.type !== "paragraph_open" ||
        tokens[i - 2]!.type !== "list_item_open"
      ) {
        continue;
      }
      const first = inline.children?.[0];
      const match = first?.type === "text" ? /^\[([ xX])\]\s+/.exec(first.content) : null;
      if (!first || !match) continue;

      first.content = first.content.slice(match[0].length);
      const box = new state.Token("html_inline", "", 0);
      box.content = `<input type="checkbox" class="task-checkbox" disabled${match[1] === " " ? "" : " checked"}> `;
      inline.children!.unshift(box);
      tokens[i - 2]!.attrJoin("class", "task-list-item");
    }
  });

  return md;
}

/** Assistant prose: smart quotes and dashes make chat answers read nicely. */
const prose = createRenderer({ typographer: true });

/**
 * Content that will be (or is) on GitHub: issue bodies, comments. GitHub
 * doesn't replace quotes or dashes, so neither does this renderer — the
 * preview must show exactly what gets written.
 */
const github = createRenderer({ typographer: false });

export function useMarkdown() {
  function render(text: string): string {
    if (!text) return "";
    return prose.render(text);
  }

  function renderGithub(text: string): string {
    if (!text) return "";
    return github.render(text);
  }

  return { render, renderGithub };
}
