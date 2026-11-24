import type { ReactNode } from "react";

/** Links may only go to pages of this app or to https sites. */
function safe(url: string): boolean {
  return url.startsWith("#/") || url.startsWith("https://");
}

const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g;

function inline(text: string, key: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const id = `${key}-${i}`;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={id}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={id}>{part.slice(2, -2)}</strong>;
    const link = part.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
    if (link) {
      if (!safe(link[2])) return link[1];
      const external = link[2].startsWith("https://");
      return (
        <a key={id} href={link[2]} {...(external ? { target: "_blank", rel: "noreferrer" } : {})}>
          {link[1]}
        </a>
      );
    }
    return part;
  });
}

/** The small subset of Markdown the assistant writes: paragraphs, bullet and numbered lists, bold, code, links. */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let paragraph: string[] = [];
  const flush = () => {
    const key = `b${blocks.length}`;
    if (paragraph.length) blocks.push(<p key={key}>{inline(paragraph.join(" "), key)}</p>);
    if (list) {
      const items = list.items.map((item, i) => <li key={i}>{inline(item, `${key}-${i}`)}</li>);
      blocks.push(list.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>);
    }
    paragraph = [];
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const item = bullet ?? numbered;
    if (item) {
      const ordered = !bullet;
      if (paragraph.length || (list as { ordered: boolean } | null)?.ordered === !ordered) flush();
      const target: { ordered: boolean; items: string[] } = list ?? { ordered, items: [] };
      target.items.push(item[1]);
      list = target;
    } else if (line.trim() === "") {
      flush();
    } else if (list && /^\s+\S/.test(raw)) {
      const items = (list as { items: string[] }).items;
      items[items.length - 1] += " " + line.trim();
    } else {
      if (list) flush();
      paragraph.push(line.replace(/^#+\s*/, "").trim());
    }
  }
  flush();
  return <div className="markdown">{blocks}</div>;
}
