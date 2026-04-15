import type { ChatMessage } from "~/types/chat";

export function useChatExport() {
  function getExportContent(msg: ChatMessage): string {
    return msg.content.trim();
  }

  /**
   * Convert a chat message array into a clean Markdown string.
   */
  function toMarkdown(
    messages: ChatMessage[],
    meta?: { repo?: string; title?: string },
  ): string {
    const lines: string[] = [];

    // Header
    if (meta?.title) {
      lines.push(`# ${meta.title}`);
    } else {
      lines.push("# Chat Export");
    }
    if (meta?.repo) {
      lines.push(`**Repository:** \`${meta.repo}\``);
    }
    lines.push(
      `**Exportiert am:** ${new Date().toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}`,
    );
    lines.push("");
    lines.push("---");
    lines.push("");

    for (const msg of messages) {
      const content = getExportContent(msg);

      // Exports should only include the actual conversation text.
      if (!content) continue;

      // Role heading
      if (msg.role === "user") {
        lines.push("## Benutzer");
      } else {
        lines.push("## Assistent");
      }
      lines.push("");

      // Message content
      lines.push(content);

      lines.push("");
      lines.push("---");
      lines.push("");
    }

    return lines.join("\n");
  }

  /**
   * Trigger a file download in the browser.
   */
  function downloadFile(content: string, filename: string, mime: string) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  /**
   * Build a safe filename slug from a title string.
   */
  function slugify(text: string): string {
    return text
      .toLowerCase()
      .replace(/[^a-z0-9äöüß]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60);
  }

  /**
   * Export the current chat as raw Markdown (.md).
   */
  function exportMarkdown(
    messages: ChatMessage[],
    meta?: { repo?: string; title?: string },
  ) {
    const md = toMarkdown(messages, meta);
    const slug = slugify(meta?.title || "chat-export");
    downloadFile(md, `${slug}.md`, "text/markdown;charset=utf-8");
  }

  /**
   * Export the current chat as PDF by rendering the Markdown into an
   * off-screen HTML document and using the browser's print-to-PDF.
   */
  function exportPdf(
    messages: ChatMessage[],
    meta?: { repo?: string; title?: string },
  ) {
    const md = toMarkdown(messages, meta);
    const { render } = useMarkdown();
    const html = render(md);

    const slug = slugify(meta?.title || "chat-export");

    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      alert("Popup-Blocker verhindert den PDF-Export. Bitte erlaube Pop-ups für diese Seite.");
      return;
    }

    printWindow.document.write(`<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <title>${meta?.title || "Chat Export"}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif;
      max-width: 800px;
      margin: 0 auto;
      padding: 40px 24px;
      color: #1a1a1a;
      font-size: 14px;
      line-height: 1.7;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }

    h1 {
      font-size: 22px;
      margin: 0 0 4px;
      border-bottom: 2px solid #e5e7eb;
      padding-bottom: 8px;
    }

    h2 {
      font-size: 15px;
      font-weight: 600;
      margin: 24px 0 8px;
      color: #374151;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    hr {
      border: none;
      border-top: 1px solid #e5e7eb;
      margin: 16px 0;
    }

    p { margin: 6px 0; }

    pre {
      background: #f3f4f6;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      padding: 12px 16px;
      overflow-x: auto;
      font-size: 12px;
      line-height: 1.5;
    }

    code {
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12px;
    }

    :not(pre) > code {
      background: #f3f4f6;
      padding: 2px 5px;
      border-radius: 3px;
    }

    details {
      background: #f9fafb;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      padding: 8px 12px;
      margin: 8px 0;
    }

    details summary {
      cursor: pointer;
      font-size: 13px;
    }

    table {
      border-collapse: collapse;
      width: 100%;
      margin: 12px 0;
      font-size: 13px;
    }

    th, td {
      border: 1px solid #e5e7eb;
      padding: 6px 10px;
      text-align: left;
    }

    th { background: #f3f4f6; font-weight: 600; }

    blockquote {
      border-left: 3px solid #d1d5db;
      margin: 8px 0;
      padding: 4px 16px;
      color: #6b7280;
    }

    ul, ol { padding-left: 24px; margin: 6px 0; }
    li { margin: 3px 0; }

    a { color: #2563eb; text-decoration: none; }

    /* Hide copy buttons from useMarkdown renderer */
    .code-block-header { display: none; }
    .code-block pre { margin: 0; }

    @media print {
      body { padding: 0; }
      pre { break-inside: avoid; }
      details { break-inside: avoid; }
      h2 { break-after: avoid; }
    }
  </style>
</head>
<body>
  ${html}
  <script>
    window.addEventListener("afterprint", () => window.close());
    // Small delay so rendering finishes before the print dialog appears
    setTimeout(() => window.print(), 400);
  <\/script>
</body>
</html>`);
    printWindow.document.close();
  }

  return {
    exportMarkdown,
    exportPdf,
    toMarkdown,
  };
}
