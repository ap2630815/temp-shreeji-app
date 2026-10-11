from weasyprint import HTML

from app.core.templating import BASE_DIR, templates


def render_pdf(template_name: str, **context) -> bytes:
    """Render a print template to PDF. base_url lets the template load the bundled Gujarati font from /static."""
    html = templates.get_template(template_name).render(**context)
    return HTML(string=html, base_url=str(BASE_DIR)).write_pdf()
