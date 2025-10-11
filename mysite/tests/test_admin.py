def test_admin_login_page_accessible(client):
    resp = client.get("/admin/login/")
    # обычно 200; иногда редирект 302 на /admin/login/?next=/admin/
    assert resp.status_code in (200, 302)
