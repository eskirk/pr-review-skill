#!/usr/bin/env python3
"""Local PR inbox dashboard: open PRs assigned to or awaiting review from the
current GitHub user, cross-referenced with the pr-review-tracker registry.

Read-only against GitHub. State lives in ``dashboard.json`` next to the
tracker's own registry; the HTML page is regenerated from it on every
mutation. Do not edit either by hand.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import fcntl
import threading
from contextlib import contextmanager
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_review_tracker as tracker  # noqa: E402
from agent_options import CODEX_MODELS, CODEX_EFFORTS, CODEX_MODEL_EFFORTS, CLAUDE_MODELS, CLAUDE_EFFORTS
from review_markdown import render as render_review_markdown  # noqa: E402


REASONS = {
    "assignee": "--assignee",
    "review-requested": "--review-requested",
    "author": "--author",
}
SEARCH_JSON_FIELDS = "url,title,repository,number,isDraft,createdAt,updatedAt,author"
# `gh pr list` (unlike `gh search prs`) has no `repository` field — it's
# implied by --repo. upsert() derives owner/repository from the URL either
# way, so this doesn't lose anything.
PR_LIST_JSON_FIELDS = "url,title,number,isDraft,createdAt,updatedAt,author"
STALE_RUN_HOURS = 6.0
DETAILS_REUSE_SECONDS = 3600
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765


class DashboardError(RuntimeError):
    pass


_state_lock = threading.RLock()


@contextmanager
def state_lock():
    # Serializes CLI and threaded HTTP read/modify/write transactions.
    with _state_lock:
        with (tracker.tracker_root() / "dashboard.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def serialized(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with state_lock():
            return func(*args, **kwargs)
    return wrapped


def dashboard_path() -> Path:
    return tracker.tracker_root() / "dashboard.json"


def html_path() -> Path:
    return tracker.tracker_root() / "dashboard.html"


def load_dashboard() -> dict[str, Any]:
    data = tracker.read_json(dashboard_path(), required=False)
    data.setdefault("prs", {})
    return data


def save_dashboard(data: dict[str, Any]) -> None:
    data["updated_at"] = tracker.utc_now()
    tracker.atomic_write(dashboard_path(), data)


AGENTS = ("claude", "codex")
DEFAULT_CONFIG = {"agent": "claude", "model": "", "effort": "", "watched_repos": [], "host_execution_repos": []}
REPO_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+$")


def config_path() -> Path:
    return tracker.tracker_root() / "dashboard_config.json"


def load_config() -> dict[str, Any]:
    stored = tracker.read_json(config_path(), required=False)
    merged = {**DEFAULT_CONFIG, **stored}
    merged["watched_repos"] = list(stored.get("watched_repos", []))
    merged["host_execution_repos"] = list(stored.get("host_execution_repos", []))
    profiles = {agent: {"model": "", "effort": ""} for agent in AGENTS}
    for agent, profile in stored.get("agent_profiles", {}).items():
        if agent in profiles:
            profiles[agent].update({k: str(profile.get(k, "")) for k in ("model", "effort")})
    selected = merged["agent"] if merged["agent"] in AGENTS else "claude"
    if selected not in stored.get("agent_profiles", {}):
        profiles[selected] = {k: str(stored.get(k, "")) for k in ("model", "effort")}
    if 'ai' in stored:
        review = stored['ai']['review']
        selected, profiles = review['provider'], review['profiles']
    merged.update(agent=selected, agent_profiles=profiles, **profiles[selected])
    return merged


# Backward-compatible name used by the agent-config call sites below.
load_agent_config = load_config


def save_agent_config(agent: str, model: str, effort: str) -> None:
    import ai_settings
    if agent not in AGENTS:
        raise DashboardError(f"Unknown agent: {agent!r}")
    settings = ai_settings.load()
    revision = ai_settings.revision(settings)
    settings['review']['provider'] = agent
    settings['review']['profiles'][agent] = {'model': model.strip(), 'effort': effort.strip()}
    try:
        ai_settings.save(settings, revision)
    except ValueError as error:
        raise DashboardError(str(error)) from error


def normalize_repo(value: str) -> str:
    value = value.strip().strip("/")
    if value.lower().startswith("https://github.com/"):
        value = value[len("https://github.com/"):]
    value = value.removesuffix(".git")
    if not REPO_PATTERN.match(value):
        raise DashboardError(f"Expected 'owner/repo', got: {value!r}")
    return value


@serialized
def add_watched_repo(repo: str) -> str:
    canonical = normalize_repo(repo)
    config = load_config()
    if canonical not in config["watched_repos"]:
        config["watched_repos"].append(canonical)
        tracker.atomic_write(config_path(), config)
    return canonical


@serialized
def remove_watched_repo(repo: str) -> str:
    canonical = normalize_repo(repo)
    config = load_config()
    if canonical in config["watched_repos"]:
        config["watched_repos"].remove(canonical)
        tracker.atomic_write(config_path(), config)
    return canonical


def normalize_host_pattern(value: str) -> str:
    """owner/repo, or owner/* for every repository of that owner."""
    value = value.strip().strip("/")
    if value.endswith("/*"):
        owner = normalize_repo(value[:-2] + "/x").split("/")[0]
        return owner + "/*"
    return normalize_repo(value)


@serialized
def add_host_execution_repo(repo: str) -> str:
    """Trust a repository's PR checks to run outside the verification sandbox."""
    canonical = normalize_host_pattern(repo)
    config = load_config()
    if canonical.lower() not in {item.lower() for item in config["host_execution_repos"]}:
        config["host_execution_repos"].append(canonical)
        tracker.atomic_write(config_path(), config)
    return canonical


@serialized
def remove_host_execution_repo(repo: str) -> str:
    canonical = normalize_host_pattern(repo)
    config = load_config()
    remaining = [item for item in config["host_execution_repos"] if item.lower() != canonical.lower()]
    if remaining != config["host_execution_repos"]:
        config["host_execution_repos"] = remaining
        tracker.atomic_write(config_path(), config)
    return canonical


def explainer_output_root() -> Path:
    return (Path.home() / ".local" / "share" / "explain-diff").resolve()


def discover_claude_options() -> tuple[list[str], list[str]]:
    """Return maintained presets without invoking a CLI during dashboard loads."""
    return CLAUDE_MODELS, CLAUDE_EFFORTS


def gh_executable() -> str:
    return os.environ.get("PR_REVIEW_TRACKER_GH", "gh")


def run_gh_search(reason: str) -> list[dict[str, Any]]:
    flag = REASONS[reason]
    try:
        result = subprocess.run(
            [
                gh_executable(),
                "search",
                "prs",
                "--state=open",
                f"{flag}=@me",
                "--json",
                SEARCH_JSON_FIELDS,
                "--limit",
                "100",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise DashboardError("GitHub CLI is not available") from error
    except subprocess.TimeoutExpired as error:
        raise DashboardError(f"GitHub search timed out for {reason}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise DashboardError(f"GitHub search failed for {reason}: {detail}")
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as error:
        raise DashboardError(f"GitHub returned invalid search data for {reason}") from error
    if not isinstance(payload, list):
        raise DashboardError(f"GitHub returned invalid search data for {reason}")
    return payload


def run_gh_pr_list(repo: str) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            [
                gh_executable(),
                "pr",
                "list",
                "--repo",
                repo,
                "--state=open",
                "--json",
                PR_LIST_JSON_FIELDS,
                "--limit",
                "100",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise DashboardError("GitHub CLI is not available") from error
    except subprocess.TimeoutExpired as error:
        raise DashboardError(f"Listing PRs timed out for {repo}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise DashboardError(f"Listing PRs failed for {repo}: {detail}")
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as error:
        raise DashboardError(f"GitHub returned invalid PR list data for {repo}") from error
    if not isinstance(payload, list):
        raise DashboardError(f"GitHub returned invalid PR list data for {repo}")
    return payload


def fetch_pr_details(canonical: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [gh_executable(), "pr", "view", canonical, "--json",
             "reviews,comments,createdAt,updatedAt,headRefOid,baseRefOid,title,body,additions,deletions,changedFiles"],
            capture_output=True, text=True, timeout=30, check=False)
        if result.returncode:
            raise DashboardError(f"Could not refresh details for {canonical}")
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise DashboardError(f"Could not refresh details for {canonical}: {error}") from error


def command_refresh(_args: argparse.Namespace) -> None:
    # Refresh is read-only against GitHub. Retention remains an explicit tracker operation.
    with (tracker.tracker_root() / "refresh.lock").open("a") as refresh_lock:
        try:
            fcntl.flock(refresh_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DashboardError("A GitHub refresh is already running.")
        _refresh_sources()
    import dashboard_triage
    dashboard_triage.maintain()
    dashboard_triage.start()


def normalize_author_login(login: str) -> str:
    # GitHub search uses app/name; GraphQL PR lists use name[bot].
    return login[4:] + "[bot]" if login.startswith("app/") else login


def fetch_author_profile(login: str) -> dict[str, Any]:
    """Fetch optional display metadata; profile failures never block the inbox."""
    try:
        result = subprocess.run(
            [gh_executable(), "api", "users/" + quote(login, safe="")],
            capture_output=True, text=True, timeout=15, check=False)
        if result.returncode == 0:
            profile = json.loads(result.stdout)
            if isinstance(profile, dict):
                return {"author_name": profile.get("name") or login,
                        "author_avatar_url": profile.get("avatar_url") or ""}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return {}


def author_profiles(logins, cached):
    """Reuse profiles for seven days; retry missing profiles next refresh."""
    now = time.time()
    profiles = {login: dict(cached.get(login, {})) for login in {normalize_author_login(value) for value in logins} if login}
    pending = [login for login, profile in profiles.items()
               if now - profile.get("checked_at", 0) > 7 * 86400]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for login, result in zip(pending, pool.map(fetch_author_profile, pending)):
            if result:
                profiles[login] = {**result, "checked_at": now}
    return profiles


def _refresh_sources() -> None:
    now = tracker.utc_now()
    snapshot = load_dashboard()
    config = load_config()
    sources = list(REASONS) + ["repo:" + repo for repo in config["watched_repos"]]
    warnings, observed, complete = [], {}, set()

    def fetch(source):
        try:
            items = run_gh_pr_list(source[5:]) if source.startswith("repo:") else run_gh_search(source)
            return source, items, None
        except DashboardError as error:
            return source, [], str(error)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for source, items, error in pool.map(fetch, sources):
            if error:
                warnings.append(error)
            elif len(items) < 100:
                complete.add(source)
            else:
                warnings.append(f"{source}: showing the first 100 results; existing entries were preserved.")
            for item in items:
                try:
                    url, owner, repo, number = tracker.canonical_pr_url(item.get("url", ""))
                except tracker.TrackerError:
                    continue
                value = observed.setdefault(url, {"sources": set(), "item": item,
                    "owner": owner, "repository": repo, "number": number})
                value["sources"].add(source)

    # Absence only establishes removal for sources that returned a complete result.
    def previous_sources(entry):
        if "sources" in entry:
            return set(entry["sources"])
        return {"repo:" + entry.get("owner", "") + "/" + entry.get("repository", "")
                if r == "watched-repo" else r for r in entry.get("reasons", [])}

    def details_current(url):
        # Search results carry updatedAt; unchanged PRs reuse details for up to an hour.
        entry, updated = snapshot["prs"].get(url, {}), observed[url]["item"].get("updatedAt")
        try:
            # Entries saved before PR sizes were recorded get one detailed fetch.
            return bool(updated and entry.get("pr_updated_at") and entry.get("head_sha") and "additions" in entry
                        and tracker.parse_time(entry["pr_updated_at"]) == tracker.parse_time(updated)
                        and tracker.parse_time(now) - tracker.parse_time(entry["details_checked_at"])
                        < timedelta(seconds=DETAILS_REUSE_SECONDS))
        except (KeyError, tracker.TrackerError):
            return False
    detail_urls = {u for u in observed if not snapshot["prs"].get(u, {}).get("hidden") and not details_current(u)}
    my_login = current_login()
    details = {}
    def detail(url):
        try:
            return url, fetch_pr_details(url), None
        except DashboardError as error:
            return url, None, str(error)
    with ThreadPoolExecutor(max_workers=6) as pool:
        for url, payload, error in pool.map(detail, sorted(detail_urls)):
            if error:
                warnings.append(error)
            else:
                details[url] = payload

    logins = {(value["item"].get("author") or {}).get("login", "") for value in observed.values()}
    logins.update(entry.get("author_login", "") for entry in snapshot["prs"].values())
    profiles = author_profiles(logins, snapshot.get("author_profiles", {}))

    with state_lock():
        data = load_dashboard()  # Preserve hiding changed during the network work.
        entries = data["prs"]
        current_sources = set(REASONS) | {"repo:" + repo for repo in load_config()["watched_repos"]}
        complete.intersection_update(current_sources)
        for url in set(entries) | set(observed):
            old = entries.get(url, {})
            found = observed.get(url)
            old_sources = previous_sources(old)
            membership = (old_sources - complete) & current_sources
            if found:
                membership |= found["sources"] & current_sources
            if not membership:
                entries.pop(url, None)
                continue
            entry = dict(old)
            if found:
                item = found["item"]
                entry.update(owner=found["owner"], repository=found["repository"],
                    number=found["number"], title=item.get("title", ""),
                    author_login=normalize_author_login((item.get("author") or {}).get("login", "")),
                    is_draft=bool(item.get("isDraft")), last_seen_at=now)
                # Search sources contain only open PRs. Release an expired snooze
                # only after this refresh observed the PR; failed sources keep it asleep.
                until = entry.get("snoozed_until")
                if until and tracker.parse_time(until) <= tracker.parse_time(now):
                    entry.pop("snoozed_until", None)
                if item.get("createdAt"):
                    entry["pr_created_at"] = item["createdAt"]
            entry.setdefault("first_seen_at", now)
            entry.setdefault("hidden", False)
            entry["sources"] = sorted(membership)
            entry["reasons"] = sorted({"watched-repo" if x.startswith("repo:") else x for x in membership})
            if url in details:
                payload = details[url]
                if payload.get("createdAt"):
                    entry["pr_created_at"] = payload["createdAt"]
                entry["pr_updated_at"] = payload.get("updatedAt", "")
                entry["head_sha"] = payload.get("headRefOid", "")
                entry["base_sha"] = payload.get("baseRefOid", "")
                for key, field in (("additions", "additions"), ("deletions", "deletions"), ("changed_files", "changedFiles")):
                    if isinstance(payload.get(field), int):
                        entry[key] = payload[field]
                import dashboard_triage
                entry["triage_context_hash"] = dashboard_triage.context_hash(payload.get("title", entry.get("title", "")), payload.get("body") or "")
                entry["details_checked_at"] = now
                if my_login:
                    reviews = [r for r in payload.get("reviews", [])
                               if (r.get("author") or {}).get("login") == my_login
                               and r.get("submittedAt") and r.get("state") != "PENDING"]
                    last = max(reviews, key=lambda r:r["submittedAt"], default={})
                    comments = [c.get("createdAt", "") for c in payload.get("comments", [])
                                if (c.get("author") or {}).get("login") == my_login]
                    entry["my_review_state"] = last.get("state", "")
                    entry["my_review_at"] = last.get("submittedAt", "")
                    entry["my_comment_at"] = max(comments, default="")
                    entry["reviewed_by_me_at"] = entry["my_review_at"]
            entries[url] = entry
        data["author_profiles"] = profiles
        data["last_refresh_attempt_at"] = now
        if not warnings:
            data["last_github_refresh_at"] = now
        data["refresh_warnings"] = warnings
        save_dashboard(data)
    rerender_from_dashboard()
    print(f"PR inbox refreshed: {len(observed)} PRs returned, {len(warnings)} warnings.")


def current_login() -> str:
    try:
        result = subprocess.run(
            [gh_executable(), "api", "user", "-q", ".login"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def latest_runs_by_pr() -> dict[str, dict[str, Any]]:
    runs, _errors = tracker.load_all_runs(STALE_RUN_HOURS)
    latest_by_pr: dict[str, dict[str, Any]] = {}
    for run in runs:
        url = run.get("pr_url", "")
        if url and url not in latest_by_pr:
            latest_by_pr[url] = run
    return latest_by_pr


def latest_run_status(pr_url: str) -> dict[str, Any] | None:
    canonical, _owner, _repository, _number = tracker.canonical_pr_url(pr_url)
    return latest_runs_by_pr().get(canonical)


def compute_review_state(entries):
    from dashboard_runtime import collect_artifacts
    runs, _ = tracker.load_all_runs(STALE_RUN_HOURS)
    state, activity, links = {}, {}, {}
    for url, entry in entries.items():
        state[url] = "mine" if "author" in entry.get("reasons", []) else (
            "reviewed" if entry.get("my_review_at") else "needs-review")
        activity[url] = bool(entry.get("my_review_at") and entry.get("pr_updated_at", "") > entry["my_review_at"])
        artifacts = collect_artifacts([r for r in runs if r.get("pr_url") == url])
        links[url] = {name: value["path"] for name, value in artifacts.items()}
    return state, activity, links


def command_hide(args: argparse.Namespace) -> None:
    set_flag(args.pr_url, "hidden", True)


def command_unhide(args: argparse.Namespace) -> None:
    set_flag(args.pr_url, "hidden", False)


def command_set_config(args: argparse.Namespace) -> None:
    save_agent_config(args.agent, args.model or "", args.effort or "")
    data = load_dashboard()
    review_state, new_activity, review_links = compute_review_state(data["prs"])
    render_html(data["prs"], review_state, new_activity, review_links, [])
    config = load_agent_config()
    print(
        f"agent config: agent={config['agent']} "
        f"model={config['model'] or '(default)'} effort={config['effort'] or '(default)'}"
    )


def rerender_from_dashboard() -> None:
    data = load_dashboard()
    review_state, new_activity, review_links = compute_review_state(data["prs"])
    render_html(data["prs"], review_state, new_activity, review_links, [])


def command_add_repo(args: argparse.Namespace) -> None:
    canonical = add_watched_repo(args.repo)
    rerender_from_dashboard()
    print(f"watching: {canonical} (its PRs show up after the next refresh)")


def command_remove_repo(args: argparse.Namespace) -> None:
    canonical = remove_watched_repo(args.repo)
    print(f"no longer watching: {canonical} (its PRs drop off on the next refresh)")
    rerender_from_dashboard()


@serialized
def set_snooze(pr_url: str, days: int | None) -> dict:
    if days is not None and (type(days) is not int or days not in (1, 2, 7)):
        raise DashboardError("Choose 1 day, 2 days, or 1 week.")
    canonical, *_ = tracker.canonical_pr_url(pr_url)
    data = load_dashboard()
    entry = data["prs"].get(canonical)
    if entry is None:
        raise DashboardError(f"PR is not tracked in the dashboard: {canonical}")
    if days is None:
        entry.pop("snoozed_until", None)
    else:
        if entry.get("hidden"):
            raise DashboardError("Restore this hidden PR before snoozing it.")
        entry["snoozed_until"] = (tracker.parse_time(tracker.utc_now()) + timedelta(days=days)).isoformat(timespec="seconds")
    save_dashboard(data)
    return {"ok": True, "snoozed_until": entry.get("snoozed_until")}


@serialized
def set_flag(pr_url: str, flag: str, value: bool) -> None:
    if flag != "hidden":
        raise DashboardError(f"Unknown preference: {flag}")
    canonical, _owner, _repository, _number = tracker.canonical_pr_url(pr_url)
    data = load_dashboard()
    entries = data["prs"]
    if canonical not in entries:
        raise DashboardError(f"PR is not tracked in the dashboard: {canonical}")
    entries[canonical].pop("snoozed_until", None)
    entries[canonical][flag] = value
    entries[canonical][f"{flag}_at"] = tracker.utc_now() if value else None
    save_dashboard(data)
    review_state, new_activity, review_links = compute_review_state(entries)
    render_html(entries, review_state, new_activity, review_links, [])
    verb = ("hidden", "unhidden")
    print(f"{verb[0] if value else verb[1]}: {canonical}")


def server_url() -> str:
    return f"http://{SERVER_HOST}:{SERVER_PORT}/"


def server_reachable() -> bool:
    try:
        urllib.request.urlopen(server_url(), timeout=1)
        return True
    except (urllib.error.URLError, OSError):
        return False


def start_server_detached() -> None:
    server_script = Path(__file__).resolve().parent / "pr_server.py"
    subprocess.Popen(
        [sys.executable, str(server_script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def command_open(_args: argparse.Namespace) -> None:
    if not server_reachable():
        start_server_detached()
        for _ in range(20):
            time.sleep(0.25)
            if server_reachable():
                break
    if not html_path().exists():
        command_refresh(argparse.Namespace())
    opener = "/usr/bin/open" if sys.platform == "darwin" else "xdg-open"
    subprocess.run([opener, server_url()], check=False)


def local_checkout_hint() -> str:
    root = Path(os.environ.get("PR_REVIEW_LOCAL_DEV_ROOT") or Path.home() / "Development").expanduser().absolute()
    return (
        f"Before creating a fresh temporary clone, check under {root} "
        "for a local checkout of this same repository (verify its origin remote "
        "actually matches this PR's owner/repo — don't just match on directory "
        "name) and, if found, use a detached git worktree from it per the "
        "isolated-checkout strategy instead of cloning again. Only fall back to "
        "a temporary clone when no matching local checkout is found."
    )


def explainer_prompt(pr_url: str) -> str:
    """Compatibility for old tabs/clients: all launches now run one review."""
    return full_review_prompt(pr_url)


def full_review_prompt(pr_url: str) -> str:
    from review_context import familiarity_prompt
    return (
        f"Follow the installed pr-review skill to fully review and explain "
        f"this pull request: {pr_url}\n\n"
        f"{familiarity_prompt(pr_url)}\n\n"
        f"{local_checkout_hint()}\n\n"
        "Review every changed file and relevant callers/contracts. Produce one "
        "self-contained review.html: explain the change at the top, then include "
        "verified findings, copyable draft comments, and validation evidence. "
        "Register it as review-html with the pr-review-tracker for the dashboard. "
        "Do not automatically open the report or launch an external browser. "
        "Do not produce a separate explainer HTML or publish to GitHub."
    )


def update_review_prompt(pr_url: str) -> str:
    from review_context import familiarity_prompt
    return (
        f"Follow the installed pr-review skill to update the existing AI review of "
        f"this pull request: {pr_url}\n\n"
        f"{familiarity_prompt(pr_url)}\n\n"
        f"{local_checkout_hint()}\n\n"
        "New commits arrived after the last finished AI review. Read the skill's "
        "references/update-review.md and this run's update-context.json first. "
        "Re-check every previous finding at the new head, review the new commits "
        "and the code they affect, and update only the explanation sections they "
        "touch. Widen to a full review when the evidence calls for it, and say so. "
        "Produce one self-contained review.html for the new head, including what "
        "changed since the last review. Register it as review-html with the "
        "pr-review-tracker for the dashboard. Do not automatically open the report "
        "or launch an external browser. Do not publish to GitHub."
    )


def previous_review_note(context_path) -> str:
    return (
        f"\n\nA previous AI review of this PR exists; {context_path} points to it. "
        "Run the full review as usual; its reviewers do not see the previous review. "
        "Also follow 'Full review with a previous review' in references/update-review.md "
        "to record what happened to each previous finding."
    )


DISPLAY_TZ = ZoneInfo("Europe/Berlin")


def format_local(iso_timestamp: str) -> str:
    if not iso_timestamp:
        return ""
    try:
        moment = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return iso_timestamp
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


_MD_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
# One pass covering both markdown [text](url) links and bare https:// URLs
# (review.md often just pastes a raw permalink, not markdown link syntax),
# so a bare URL's own scheme/slashes can never be mis-parsed as, or
# double-processed against, the markdown-link alternative.
_MD_LINK_OR_BARE_URL = re.compile(
    r"\[([^\]]+)\]\(((?:https?://|/)[^)\s]+)\)" r"|(https?://[^\s<>\"')\]]+)"
)


def _render_link_or_bare_url(match: re.Match) -> str:
    if match.group(1) is not None:
        url = match.group(2)
        if url.startswith('/'):
            url = '/artifact?path=' + quote(html.unescape(url), safe='')
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{match.group(1)}</a>'
    url = match.group(3)
    trailing = ""
    while url and url[-1] in ".,;:!?":
        trailing = url[-1] + trailing
        url = url[:-1]
    return f'<a href="{url}" target="_blank" rel="noopener">{url}</a>{trailing}'


def markdown_inline_to_html(text: str) -> str:
    escaped = esc(text)
    placeholders: list[str] = []

    def stash_code(match: re.Match) -> str:
        placeholders.append(f"<code>{match.group(1)}</code>")
        return f"\x00{len(placeholders) - 1}\x00"

    escaped = _MD_INLINE_CODE.sub(stash_code, escaped)
    escaped = _MD_LINK_OR_BARE_URL.sub(_render_link_or_bare_url, escaped)
    escaped = _MD_BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _MD_ITALIC.sub(r"<em>\1</em>", escaped)
    for index, value in enumerate(placeholders):
        escaped = escaped.replace(f"\x00{index}\x00", value)
    return escaped


def markdown_to_html(text: str) -> str:
    """Render the supported review Markdown, escaping arbitrary source HTML."""
    return render_review_markdown(text, markdown_inline_to_html, esc)


def render_markdown_page(title: str, source_path: Path, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #ffffff; --fg: #1b1b1f; --muted: #6b7280; --border: #e5e7eb; --code-bg: #f3f4f6;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #16171b; --fg: #e5e7eb; --muted: #9ca3af; --border: #2d2f36; --code-bg: #1f2024; }}
  }}
  body {{ background: var(--bg); color: var(--fg); font: 15px/1.55 system-ui, sans-serif; margin: 0; padding: 32px; max-width: 860px; overflow-wrap: anywhere; }}
  h1, h2, h3, h4 {{ line-height: 1.25; }}
  h1 {{ font-size: 22px; }}
  h2 {{ font-size: 18px; border-bottom: 1px solid var(--border); padding-bottom: 6px; margin-top: 32px; }}
  h3 {{ font-size: 15px; margin-top: 24px; }}
  a {{ color: inherit; }}
  code {{ background: var(--code-bg); border-radius: 4px; padding: 1px 5px; font-size: 0.9em; }}
  pre {{ background: var(--code-bg); border-radius: 8px; padding: 12px 14px; overflow-x: auto; }}
  pre code {{ background: none; padding: 0; }}
  ul, ol {{ padding-left: 22px; }}
  li {{ margin: 4px 0; }}
  hr {{ border: none; border-top: 1px solid var(--border); margin: 24px 0; }}
  blockquote {{ border-left: 3px solid var(--border); margin: 16px 0; padding: 0 16px; }}
  .table-scroll {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
  th, td {{ border: 1px solid var(--border); padding: 8px 10px; vertical-align: top; }}
  details {{ margin: 16px 0; padding: 12px; border: 1px solid var(--border); border-radius: 8px; }}
  summary {{ cursor: pointer; font-weight: 600; }}
  .review-comment {{ border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin: 16px 0; }}
  .copy-comment {{ color: var(--fg); background: var(--code-bg); border: 1px solid var(--border); border-radius: 6px; padding: 7px 12px; cursor: pointer; }}
  .copy-comment:focus-visible, summary:focus-visible {{ outline: 2px solid currentColor; outline-offset: 3px; }}
  .copy-status {{ margin-left: 12px; font-size: 13px; }}
  .comment-source:not([hidden]) {{ display: block; width: 100%; min-height: 140px; margin-top: 12px; }}
  pre {{ white-space: pre; }}
  @media (max-width: 600px) {{ body {{ padding: 16px; }} }}
  footer {{ color: var(--muted); font-size: 12px; margin-top: 32px; }}
</style>
</head>
<body>
{body}
<footer>Rendered from {esc(str(source_path))}</footer>
<script>
document.addEventListener('click', async (event) => {{
  const button = event.target.closest('.copy-comment');
  if (!button) return;
  const section = button.closest('.review-comment');
  const source = section.querySelector('.comment-source');
  const status = section.querySelector('.copy-status');
  try {{
    await navigator.clipboard.writeText(source.value);
    status.textContent = 'Copied';
  }} catch (error) {{
    source.hidden = false;
    source.focus();
    source.select();
    status.textContent = 'Select and copy the Markdown below.';
  }}
}});
</script>
</body>
</html>
"""


def render_html(entries=None, review_state=None, new_activity=None, review_links=None, warnings=None):
    template = Path(__file__).resolve().parent.parent / "assets" / "dashboard.html"
    html_path().write_text(template.read_text(encoding="utf-8"), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("refresh").set_defaults(func=command_refresh)

    hide_parser = subparsers.add_parser("hide")
    hide_parser.add_argument("pr_url")
    hide_parser.set_defaults(func=command_hide)

    unhide_parser = subparsers.add_parser("unhide")
    unhide_parser.add_argument("pr_url")
    unhide_parser.set_defaults(func=command_unhide)

    config_parser = subparsers.add_parser("set-config")
    config_parser.add_argument("--agent", choices=AGENTS, required=True)
    config_parser.add_argument("--model", default="")
    config_parser.add_argument("--effort", default="")
    config_parser.set_defaults(func=command_set_config)

    add_repo_parser = subparsers.add_parser("add-repo")
    add_repo_parser.add_argument("repo")
    add_repo_parser.set_defaults(func=command_add_repo)

    remove_repo_parser = subparsers.add_parser("remove-repo")
    remove_repo_parser.add_argument("repo")
    remove_repo_parser.set_defaults(func=command_remove_repo)

    subparsers.add_parser("open").set_defaults(func=command_open)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (DashboardError, tracker.TrackerError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
