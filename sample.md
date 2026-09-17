---
subtitle: A torture test for the renderer, covering every construct a document might reasonably contain.
kicker: Pipeline test
---

# Typography and Rendering Test

This opening paragraph exists to check the measure, the leading, and how a serif body face sits against the background. It should feel like something you'd actually want to read on a phone at night -- not a GitHub README. The line length is capped near sixty-eight characters, which is the range where the eye tracks reliably from one line to the next without losing its place.

Inline formatting: **bold text**, *italic text*, ***both at once***, `inline_code()`, ~~struck through~~, a [link to somewhere](https://example.com), and an em dash -- rendered by smartypants from a double hyphen.

## Headings and hierarchy

Second-level headings get a hairline rule above them to break the page into sections. Hover one on desktop and an anchor link fades in on the left.

### Third level

Third-level headings are smaller and carry no rule, so a section can have internal structure without feeling chopped up.

#### Fourth level

And a fourth level, for when things get genuinely nested.

## Lists

An unordered list:

- First item, kept short.
- Second item, which runs considerably longer to verify that wrapped list items align correctly against the marker rather than sliding back under it.
- Third item with nesting:
  - A nested child
  - Another nested child
    - And one level deeper

An ordered list:

1. Fetch the source document
2. Render it to semantic HTML
3. Wrap it in the theme
4. Commit and push

A task list:

- [x] Write the stylesheet
- [x] Write the publisher
- [ ] Ship it

A definition list:

Measure
:   The length of a line of text, ideally 45 to 75 characters.

Leading
:   The vertical space between baselines.

## Quotations

> Typography is the craft of endowing human language with a durable visual form.
>
> The reader should be able to forget the type entirely and simply read.

## Code

Inline `const x = 42` sits within a sentence. Fenced blocks get syntax highlighting, a copy button on hover, and a horizontal scrollbar rather than wrapping:

```python
def publish(path: Path, slug: str | None = None) -> str:
    """Render a document and return its live URL."""
    text = path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(text)
    html_body, toc = render_markdown(body)
    return deploy(html_body, slug or slugify(path.stem), toc=toc)
```

```javascript
const observer = new IntersectionObserver((entries) => {
  entries.forEach((e) => e.isIntersecting && highlight(e.target.id));
}, { rootMargin: "-80px 0px -70% 0px" });
```

```bash
./publish.py ~/notes/quarterly-review.md
# => https://coldbeanage.github.io/read/quarterly-review/
```

## Tables

| Component | Purpose | Cost |
|---|---|---|
| GitHub Pages | Static hosting | Free |
| `publish.py` | Render + deploy | Free |
| Pygments | Syntax highlighting | Free |
| Custom domain | Optional vanity URL | ~$12/yr |

## Admonitions

!!! note "Worth knowing"
    Admonition blocks are available for asides that shouldn't interrupt the main argument.

!!! warning "Careful"
    This one signals risk. It uses a different accent colour from the note above.

!!! tip
    And an untitled tip, which falls back to a generic label.

## Footnotes

Claims that need a citation can carry one[^1], and the reference collects at the bottom of the page[^2].

[^1]: Footnotes render in a separate block below a rule, at a smaller size.
[^2]: With a back-reference arrow to return you to your place in the text.

## A long passage

To judge vertical rhythm properly you need more than a couple of lines, so here is a stretch of continuous prose. The spacing between paragraphs should be large enough to signal a break in thought but not so large that the page feels sparse and scrolling becomes a chore. Roughly one and three-quarter times the line height tends to land in the right place.

Dark mode is not simply an inversion. Pure white on pure black produces halation, where the light text appears to bleed into the surrounding darkness, and long passages become genuinely tiring. The dark palette here uses an off-black background and a warm off-white foreground, which holds contrast without the glare.

Finally, the reading progress bar at the very top gives a sense of how much remains, and the sidebar contents panel tracks your position as you scroll. Neither is essential, but both reduce the small anxiety of not knowing how long a document is going to take.

---

That's the end of the test.
