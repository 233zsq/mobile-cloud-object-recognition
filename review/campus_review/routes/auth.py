"""HTTP adapters for auth review operations; endpoint names stay stable."""

import secrets
from flask import g, redirect, render_template, request, session, url_for
from ..database import db, event
from ..security import require
from ..services.accounts import (
    authenticate,
    consume_invitation,
    create_invitation,
    invitation,
)
from ..validation import safe, text


def login():
    if request.method == "POST":
        username = request.form.get("username", "")[:80]
        password = request.form.get("password", "")[:1024]
        user = authenticate(db(), username, password, request.remote_addr)
        session.clear()
        session.update(uid=user["id"], csrf=secrets.token_urlsafe(32))
        session.permanent = True
        return redirect(url_for("index"))
    return render_template("login.html")


def logout():
    if g.user:
        db().execute("DELETE FROM review_leases WHERE user_id=?", (g.user["id"],))
    session.clear()
    return redirect(url_for("login"))


def join(token):
    invite = invitation(db(), token)
    if request.method == "POST":
        username = safe(text("username"))
        password = text("password")
        consume_invitation(db(), token, invite, username, password)
        return redirect(url_for("login"))
    return render_template("join.html", role=invite["role"])


@require("admin")
def invite():
    token = create_invitation(db(), "reviewer", 7 * 86400)
    event("invite", "reviewer", {"expires_days": 7})
    return render_template(
        "invite.html", link=url_for("join", token=token, _external=True)
    )


def register(app):
    app.add_url_rule("/login", view_func=login, methods=["GET", "POST"])
    app.add_url_rule("/logout", view_func=logout, methods=["POST"])
    app.add_url_rule("/join/<token>", view_func=join, methods=["GET", "POST"])
    app.add_url_rule("/invites", view_func=invite, methods=["POST"])
