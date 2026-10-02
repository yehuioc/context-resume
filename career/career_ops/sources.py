"""只读公开岗位来源；平台存活与雇主官方核验是两种不同证据。"""
from __future__ import annotations

import copy
import hashlib
import html
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import socket
from datetime import datetime, timezone
from urllib import error, parse, request


NCSS_API = "https://www.ncss.cn/student/jobs/jobslist/ajax/"
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/"
OFFICIAL_BOARDS = {"anthropic": {"company": "Anthropic", "careers": "https://www.anthropic.com/careers/jobs"}}
VERIFICATION_STATUSES = {"employer_verified", "official_platform_live", "closed", "unknown", "failed"}
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
PROJECT_PRIVATE = Path(__file__).resolve().parents[1] / "private"
_NETWORK_HOSTS = {"www.ncss.cn", "ncss.cn", "boards-api.greenhouse.io", "www.anthropic.com", "anthropic.com"}


class SourceError(ValueError):
    """来源失败是显式错误，不能据此关闭既有岗位。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jd_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text).strip()


class _TextExtractor(HTMLParser):
    """保留块级段落，排除脚本、样式与隐藏模板；可只取指定 JD 容器。"""
    BLOCKS = {"p", "div", "pre", "li", "ul", "ol", "section", "article", "h1", "h2", "h3", "h4", "br", "hr", "tr"}
    VOID = {"br", "hr", "img", "input", "meta", "link", "source", "wbr", "area", "base", "embed", "param"}

    def __init__(self, selector=None):
        super().__init__(convert_charrefs=True)
        self.selector = selector
        self.stack = []
        self.parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent_skipped = self.stack[-1][1] if self.stack else False
        parent_selected = self.stack[-1][2] if self.stack else self.selector is None
        skipped = parent_skipped or tag in {"script", "style", "noscript", "template"} or "hidden" in attrs
        skipped = skipped or bool(set(attrs.get("class", "").split()) & {"hide", "hidden"})
        skipped = skipped or bool(re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", attrs.get("style", ""), re.I))
        selected = parent_selected or bool(self.selector and self.selector(tag, attrs))
        if selected and not skipped and tag in self.BLOCKS:
            self.parts.append("\n")
        if not skipped and tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag not in self.VOID:
            self.stack.append((tag, skipped, selected))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                _, skipped, selected = self.stack[i]
                if selected and not skipped and tag in self.BLOCKS:
                    self.parts.append("\n")
                del self.stack[i:]
                break

    def handle_data(self, data):
        skipped = self.stack[-1][1] if self.stack else False
        selected = self.stack[-1][2] if self.stack else self.selector is None
        if selected and not skipped:
            self.parts.append(data)

    def text(self):
        return _clean_text("".join(self.parts))


def extract_html(content: str) -> str:
    # Greenhouse publishes entity-encoded HTML, sometimes encoded twice.
    for _ in range(3):
        decoded = html.unescape(content)
        if decoded == content:
            break
        content = decoded
    parser = _TextExtractor()
    parser.feed(content)
    return parser.text()


def split_jd_sections(text: str) -> dict:
    """分段只引用原文；不把段落猜测改写成岗位要求。"""
    groups = {"responsibilities": [], "required": [], "preferred": [], "other": []}
    current = "other"
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.search(r"^(?:职责|工作职责|岗位职责|职位职责|工作内容|responsibilities|what you.ll do|you will)[:：]?$", line, re.I):
            current = "responsibilities"
        elif re.search(r"^(?:要求|任职要求|岗位要求|任职资格|职位要求|qualifications|requirements|you may be a good fit if you|what you bring)[:：]?$", line, re.I):
            current = "required"
        elif re.search(r"^(?:加分项|优先条件|优先|preferred qualifications|nice to have|strong candidates may also)[:：]?$", line, re.I):
            current = "preferred"
        groups[current].append(line)
    return {key: "\n".join(value) for key, value in groups.items() if value}


def validate_public_url(url: str, *, resolve: bool = False) -> str:
    """不接受本地服务、凭证 URL、非 HTTP 协议或非标准端口。"""
    try:
        parsed = parse.urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (ValueError, TypeError) as exc:
        raise SourceError("invalid source URL") from exc
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise SourceError("source URL must be public HTTP(S) without credentials")
    if port is not None and port != (443 if parsed.scheme == "https" else 80):
        raise SourceError("non-standard source URL port is forbidden")
    if host in {"localhost", "localhost.localdomain"} or "." not in host or host.endswith((".localhost", ".local", ".internal", ".lan")):
        raise SourceError("local source URL is forbidden")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise SourceError("non-public source IP is forbidden")
    if resolve:
        try:
            addresses = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError as exc:
            raise SourceError(f"cannot resolve source host: {host}") from exc
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise SourceError("source host resolves to a non-public address")
    return parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _network_url(url: str) -> str:
    url = validate_public_url(url, resolve=True)
    parsed = parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in _NETWORK_HOSTS:
        raise SourceError("automatic verification only fetches supported public HTTPS source hosts")
    return url


class _SafeRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = _network_url(parse.urljoin(req.full_url, newurl))
        if parse.urlsplit(req.full_url).hostname != parse.urlsplit(newurl).hostname:
            raise SourceError("cross-host redirect requires manual verification")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _save_response(body: bytes, evidence: dict, evidence_dir) -> dict:
    evidence = dict(evidence)
    evidence["sha256"] = hashlib.sha256(body).hexdigest()
    evidence["bytes"] = len(body)
    if evidence_dir is not None:
        directory = Path(evidence_dir).resolve()
        if not directory.is_relative_to(PROJECT_PRIVATE.resolve()):
            raise SourceError("source evidence must stay inside this project's private directory")
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        stem = f"{stamp}-{evidence['sha256'][:16]}"
        raw_path = directory / (stem + ".raw")
        meta_path = directory / (stem + ".json")
        raw_path.write_bytes(body)
        evidence["raw_path"] = str(raw_path.resolve())
        evidence["metadata_path"] = str(meta_path.resolve())
        meta_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence


def _fetch(url: str, timeout: float, evidence_dir=None) -> tuple[str, dict]:
    if not 0 < timeout <= 120:
        raise SourceError("timeout must be in (0, 120] seconds")
    url = _network_url(url)
    evidence = {"requested_url": url, "observed_at": utc_now(), "method": "GET"}
    try:
        opener = request.build_opener(_SafeRedirect())
        req = request.Request(url, headers={"User-Agent": "career-ops/0.1 public-job-reader", "Accept": "application/json,text/html;q=0.9"})
        with opener.open(req, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            evidence.update(http_status=response.status, final_url=response.geturl(), content_type=response.headers.get("Content-Type", ""))
            if len(body) > MAX_RESPONSE_BYTES:
                raise SourceError("source response exceeded 20 MiB limit")
            evidence = _save_response(body, evidence, evidence_dir)
            try:
                return body.decode("utf-8-sig"), evidence
            except UnicodeDecodeError as exc:
                raise SourceError("source response is not valid UTF-8") from exc
    except error.HTTPError as exc:
        body = exc.read(MAX_RESPONSE_BYTES)
        evidence.update(http_status=exc.code, final_url=exc.geturl(), error="http_error")
        _save_response(body, evidence, evidence_dir)
        raise SourceError(f"HTTP {exc.code} from {url}") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        evidence.update(error=type(exc).__name__, error_message=str(exc))
        _save_response(b"", evidence, evidence_dir)
        raise SourceError(f"source request failed: {url}: {exc}") from exc
    except SourceError as exc:
        evidence.update(error=type(exc).__name__, error_message=str(exc))
        _save_response(b"", evidence, evidence_dir)
        raise


def _json_fetch(url, timeout, evidence_dir):
    text, evidence = _fetch(url, timeout, evidence_dir)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError(f"invalid JSON from {url}") from exc
    if not isinstance(payload, dict):
        raise SourceError(f"expected JSON object from {url}")
    return payload, evidence


def _bounds(limit, max_pages):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise SourceError("limit must be an integer in [1, 1000]")
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 50:
        raise SourceError("max_pages must be an integer in [1, 50]")


def _date(value) -> str | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 10**11 else value, timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    return str(value) if value else None


def _employment_type(title, jd):
    if re.search(r"实习|\bintern(?:ship)?\b", title, re.I):
        return "internship"
    if re.search(r"校招|应届|graduate|new grad", title, re.I):
        return "graduate"
    if re.search(r"兼职|part[- ]time", title, re.I):
        return "part_time"
    if re.search(r"全职|full[- ]time", title + "\n" + jd, re.I):
        return "full_time"
    return "unknown"


def _work_mode(location, jd):
    text = location + "\n" + jd
    if re.search(r"不(?:接收|支持|接受).{0,8}(?:线上|远程)|(?:on[- ]site|现场实习|线下实习)", text, re.I):
        return "on_site"
    if re.search(r"hybrid|混合办公|remote[- ]friendly", location, re.I):
        return "hybrid"
    if re.search(r"remote|远程|线上实习", location, re.I) or re.search(r"支持(?:远程|线上实习)|可(?:远程|线上实习)|remote[- ]only|fully remote", jd, re.I):
        return "remote"
    return "unknown"


def _observation(**fields):
    base = {"company": "", "role_title": "", "source_channel": "manual", "source_url": "", "official_url": "", "external_id": "", "posted_at": None,
            "location": "", "work_mode": "unknown", "employment_type": "unknown", "jd_raw": "", "verification_status": "unknown", "risk_flags": [],
            "source_payload": {}, "observed_at": utc_now(), "verification_evidence": {}, "source_urls": []}
    base.update(fields)
    base["jd_hash"] = jd_hash(base["jd_raw"])
    base["jd_sections"] = split_jd_sections(base["jd_raw"])
    base["source_urls"] = list(dict.fromkeys(base.get("source_urls", []) + ([base["source_url"]] if base["source_url"] else [])))
    base["employment_type"] = _employment_type(base["role_title"], base["jd_raw"])
    base["work_mode"] = _work_mode(base["location"], base["jd_raw"])
    base["source_verified"] = base["verification_status"] in {"employer_verified", "official_platform_live"}
    base["application_verified"] = base["verification_status"] == "employer_verified"
    base["apply_url_type"] = "official_ats" if base["application_verified"] else ("official_platform" if base["verification_status"] == "official_platform_live" else "unverified")
    if not base["jd_raw"]:
        base["risk_flags"] = list(dict.fromkeys(base["risk_flags"] + ["missing_jd"]))
    return base


def _ncss_detail(text):
    jd_parser = _TextExtractor(lambda tag, attrs: tag == "pre" and "mainContent" in attrs.get("class", "").split())
    jd_parser.feed(text)
    page_parser = _TextExtractor()
    page_parser.feed(text)
    return jd_parser.text(), page_parser.text()


def _ncss_snapshot_state(obs, text):
    """在线核验和离线导入共用同一份详情判定。"""
    jd, visible = _ncss_detail(text)
    apply_parser = _TextExtractor(lambda tag, attrs: "apply" in attrs.get("class", "").split() and "disabled" not in attrs.get("class", "").split() and "disabled" not in attrs)
    apply_parser.feed(text)
    closed = bool(re.search(r"(?:职位|岗位).{0,10}(?:已下线|已关闭|已过期|停止招聘)|^已下线$", visible, re.M))
    risks = []
    if closed:
        status, reason = "closed", "visible platform detail explicitly says the position is closed"
        risks.append("closed")
    elif jd and "投递简历" in apply_parser.text():
        status, reason = "official_platform_live", "NCSS has full JD and active application block; employer identity not independently confirmed"
        risks.append("employer_origin_unconfirmed")
    else:
        status, reason = "unknown", "detail lacks full JD or demonstrable live application block"
    for field, element_id in [("role_title", "jobName"), ("company", "realCorpName")]:
        parser = _TextExtractor(lambda tag, attrs, key=element_id: attrs.get("id") == key)
        parser.feed(text)
        if parser.text() and parser.text() != obs.get(field):
            risks.append("source_identity_changed")
            status, reason = "unknown", "detail identity differs from listing observation"
    location_parser = _TextExtractor(lambda tag, attrs: "site-tag" in attrs.get("class", "").split())
    location_parser.feed(text)
    return {"jd_raw": jd, "location": location_parser.text(), "status": status, "reason": reason, "risk_flags": risks}


def _stale(posted_at):
    try:
        when = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - when).days > 90
    except (AttributeError, ValueError):
        return False


def _past_deadline(value):
    if not value:
        return False
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when < datetime.now(timezone.utc)
    except ValueError:
        raise SourceError("ATS application_deadline is invalid")


def collect_ncss(keyword: str = "", *, limit: int = 20, max_pages: int = 3, timeout: float = 15, evidence_dir=None) -> list[dict]:
    """NCSS offset 是页号，先公开列表再逐条详情；任何列表失败直接抛错。"""
    _bounds(limit, max_pages)
    jobs, seen = [], set()
    page_size = min(limit, 20)
    for page in range(1, max_pages + 1):
        url = NCSS_API + "?" + parse.urlencode({"jobName": keyword, "offset": page, "limit": page_size, "sourcesName": 0})
        payload, listing_evidence = _json_fetch(url, timeout, evidence_dir)
        data = payload.get("data")
        if payload.get("flag") is False or payload.get("errors") or not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise SourceError("NCSS returned an error or invalid jobs-list schema")
        items = data["list"]
        if not items:
            break
        before = len(seen)
        for item in items:
            if not isinstance(item, dict) or not item.get("jobId"):
                raise SourceError("NCSS list item has no jobId")
            external_id = str(item["jobId"])
            if external_id in seen:
                continue
            if not re.fullmatch(r"[A-Za-z0-9_-]+", external_id):
                raise SourceError("invalid NCSS jobId")
            seen.add(external_id)
            source_url = f"https://www.ncss.cn/student/jobs/{external_id}/detail.html"
            obs = _observation(company=str(item.get("recName", "")), role_title=str(item.get("jobName", "")), source_channel="ncss", source_url=source_url,
                               external_id=external_id, location=str(item.get("areaCodeName", "")), posted_at=_date(item.get("publishDate")),
                               source_payload={"provider": "ncss", "listing": item, "keyword": keyword, "list_url": url},
                               verification_evidence={"listing": listing_evidence})
            jobs.append(verify_observation(obs, timeout=timeout, evidence_dir=evidence_dir))
            if len(jobs) >= limit:
                return jobs
        if len(items) < page_size or len(seen) == before:
            break
    return jobs


def _board_token(board):
    if not isinstance(board, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", board):
        raise SourceError("invalid Greenhouse board token")
    return board.lower()


def _official_links(board, timeout, evidence_dir):
    registry = OFFICIAL_BOARDS.get(board)
    if not registry:
        return set(), {"reason": "no employer-origin board binding configured"}
    try:
        text, evidence = _fetch(registry["careers"], timeout, evidence_dir)
        parser = _TextExtractor()
        parser.feed(text)
        links = set()
        for link in parser.links:
            parsed = parse.urlsplit(link)
            if parsed.hostname in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and parsed.path.startswith(f"/{board}/jobs/"):
                links.add(parse.urlunsplit(("https", "job-boards.greenhouse.io", parsed.path, "", "")))
        return links, {"employer_careers": evidence, "binding": "employer career page links exact ATS job URL", "linked_job_count": len(links)}
    except SourceError as exc:
        return set(), {"reason": "employer careers origin unavailable", "error": str(exc)}


def _canonical_ats_url(url, board, external_id):
    try:
        url = validate_public_url(url)
    except SourceError:
        return ""
    parsed = parse.urlsplit(url)
    if parsed.hostname not in {"boards.greenhouse.io", "job-boards.greenhouse.io"} or parsed.path.rstrip("/") != f"/{board}/jobs/{external_id}":
        return ""
    return f"https://job-boards.greenhouse.io/{board}/jobs/{external_id}"


def _greenhouse_observation(item, board, evidence, links, origin):
    if not isinstance(item, dict) or not isinstance(item.get("id"), int) or not item.get("title"):
        raise SourceError("invalid Greenhouse job schema")
    external_id = str(item["id"])
    source_url = str(item.get("absolute_url", ""))
    canonical = _canonical_ats_url(source_url, board, external_id)
    jd = extract_html(str(item.get("content", "")))
    verified = bool(jd and canonical and canonical in links)
    posted = _date(item.get("first_published"))
    risks = [] if verified else ["employer_origin_unconfirmed"]
    if canonical == "":
        risks.append("untrusted_apply_url")
    if item.get("internal_job_id", "present") is None:
        risks.append("expression_of_interest")
    return _observation(company=str(item.get("company_name") or OFFICIAL_BOARDS.get(board, {}).get("company") or board), role_title=str(item["title"]),
                        source_channel=f"greenhouse:{board}", source_url=source_url, official_url=canonical if verified else "", external_id=external_id,
                        source_urls=[source_url, canonical] if verified else [source_url],
                        location=str((item.get("location") or {}).get("name", "")), posted_at=posted, jd_raw=jd, verification_status="employer_verified" if verified else "unknown",
                        risk_flags=risks, source_payload={"provider": "greenhouse", "board": board, "job": item},
                        verification_evidence={"ats": evidence, "employer_origin": origin, "checked_url": canonical or source_url, "status_reason": "published ATS job with exact employer-origin link" if verified else "published ATS job; employer-origin confirmation missing"})


def collect_greenhouse(board: str = "anthropic", *, limit: int = 20, max_pages: int = 1, timeout: float = 15, evidence_dir=None) -> list[dict]:
    """Greenhouse list jobs 一次返回全列表（官方协议无分页）；本地限量。"""
    _bounds(limit, max_pages)
    board = _board_token(board)
    url = f"{GREENHOUSE_API}{board}/jobs?content=true"
    payload, evidence = _json_fetch(url, timeout, evidence_dir)
    if not isinstance(payload.get("jobs"), list):
        raise SourceError("Greenhouse returned an invalid jobs-list schema")
    links, origin = _official_links(board, timeout, evidence_dir)
    return [_greenhouse_observation(item, board, evidence, links, origin) for item in payload["jobs"][:limit]]


def verify_observation(observation: dict, *, timeout: float = 15, evidence_dir=None) -> dict:
    """刷新真实详情；错误只降低核验，不清空旧 JD，也不把超时当关闭。"""
    obs = copy.deepcopy(observation)
    channel = obs.get("source_channel", "manual")
    evidence = copy.deepcopy(obs.get("verification_evidence") or {})
    evidence["verified_at"] = utc_now()
    risks = [x for x in obs.get("risk_flags", []) if x not in {"verification_failed", "closed", "missing_jd", "stale_posting"}]
    obs.update(official_url="", observed_at=utc_now(), verification_status="unknown")
    trusted_detail = False
    try:
        if channel == "ncss":
            external_id = str(obs.get("external_id", ""))
            expected = f"https://www.ncss.cn/student/jobs/{external_id}/detail.html"
            if not re.fullmatch(r"[A-Za-z0-9_-]+", external_id) or obs.get("source_url") != expected:
                raise SourceError("NCSS identity and detail URL do not match")
            trusted_detail = True
            text, detail_evidence = _fetch(expected, timeout, evidence_dir)
            evidence["detail"] = detail_evidence
            result = _ncss_snapshot_state(obs, text)
            if result["jd_raw"]:
                obs["jd_raw"] = result["jd_raw"]
            if result["location"]:
                obs["location"] = result["location"]
            obs["verification_status"] = result["status"]
            evidence["status_reason"] = result["reason"]
            risks.extend(result["risk_flags"])
        elif channel.startswith("greenhouse:"):
            board = _board_token(channel.split(":", 1)[1])
            external_id = str(obs.get("external_id", ""))
            if not external_id.isdigit() or not _canonical_ats_url(obs.get("source_url", ""), board, external_id):
                raise SourceError("Greenhouse identity and detail URL do not match")
            trusted_detail = True
            item, detail_evidence = _json_fetch(f"{GREENHOUSE_API}{board}/jobs/{external_id}", timeout, evidence_dir)
            if str(item.get("id")) != external_id:
                raise SourceError("Greenhouse detail identity mismatch")
            links, origin = _official_links(board, timeout, evidence_dir)
            refreshed = _greenhouse_observation(item, board, detail_evidence, links, origin)
            refreshed["verification_evidence"]["prior_evidence"] = evidence
            refreshed["source_urls"] = list(dict.fromkeys(obs.get("source_urls", []) + refreshed["source_urls"]))
            obs.update(refreshed)
            evidence = obs["verification_evidence"]
            risks = obs["risk_flags"]
            deadline = _date(item.get("application_deadline"))
            if _past_deadline(deadline):
                obs["verification_status"] = "closed"
                risks.append("closed")
                evidence["status_reason"] = "official ATS application_deadline has passed"
        else:
            if obs.get("source_url"):
                validate_public_url(obs["source_url"])
            evidence["status_reason"] = "unsupported/manual channel requires independent employer verification; no automatic arbitrary URL fetch"
    except SourceError as exc:
        http_code = getattr(exc.__cause__, "code", None)
        if trusted_detail and http_code in {404, 410}:
            obs["verification_status"] = "closed"
            risks.append("closed")
            evidence["status_reason"] = f"trusted job detail returned HTTP {http_code}"
        else:
            obs["verification_status"] = "failed"
            risks.append("verification_failed")
            evidence["status_reason"] = "verification failed; existing content preserved; closure not inferred"
        evidence["error"] = str(exc)
    if _stale(obs.get("posted_at")):
        risks.append("stale_posting")
    obs["risk_flags"] = list(dict.fromkeys(risks))
    obs["verification_evidence"] = evidence
    return _observation(**obs)


def import_manual(payload: dict) -> dict:
    """已有 JD 可结构化导入；调用方自称 verified/official 不构成核验证据。"""
    if not isinstance(payload, dict):
        raise SourceError("manual import requires an object")
    company = str(payload.get("company", "")).strip()
    title = str(payload.get("role_title") or payload.get("title") or "").strip()
    if not company or not title:
        raise SourceError("manual import requires company and role_title")
    url = str(payload.get("source_url") or payload.get("url") or "").strip()
    if url:
        url = validate_public_url(url)
    raw = payload.get("jd_raw") or payload.get("jd_text") or payload.get("description") or ""
    if not isinstance(raw, str):
        raise SourceError("manual JD must be text")
    jd = extract_html(raw) if re.search(r"<\w|&lt;", raw) else _clean_text(raw)
    return _observation(company=company, role_title=title, source_url=url, external_id=str(payload.get("external_id", "")), posted_at=_date(payload.get("posted_at")),
                        location=str(payload.get("location", "")), jd_raw=jd, source_channel="manual", risk_flags=["manual_unverified"],
                        source_payload={"provider": "manual", "original_channel": payload.get("source_channel", "manual"), "imported": copy.deepcopy(payload)},
                        verification_evidence={"status_reason": "user-supplied JD is preserved but is not independent employer verification", "imported_at": utc_now()})


def _read_collected_evidence(evidence: dict, expected_url: str | None = None) -> str:
    """只读本项目证据；hash 证明字节一致，URL/语义核查证明它确实属于此岗位。"""
    if not isinstance(evidence, dict) or not evidence.get("raw_path") or not evidence.get("metadata_path"):
        raise SourceError("collected observation lacks raw response metadata")
    private = PROJECT_PRIVATE.resolve()
    raw_path, meta_path = Path(evidence["raw_path"]).resolve(), Path(evidence["metadata_path"]).resolve()
    if not raw_path.is_relative_to(private) or not meta_path.is_relative_to(private):
        raise SourceError("collected evidence path escapes project private boundary")
    try:
        body = raw_path.read_bytes()
        metadata = json.loads(meta_path.read_text("utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceError("collected evidence is missing or invalid") from exc
    if hashlib.sha256(body).hexdigest() != evidence.get("sha256") or metadata.get("sha256") != evidence.get("sha256"):
        raise SourceError("collected evidence hash mismatch")
    for key in ("requested_url", "http_status", "final_url"):
        if metadata.get(key) != evidence.get(key):
            raise SourceError(f"collected evidence metadata mismatch: {key}")
    url = validate_public_url(str(evidence.get("requested_url", "")))
    parsed = parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in _NETWORK_HOSTS:
        raise SourceError("collected evidence is not a supported HTTPS source")
    if expected_url and url != expected_url:
        raise SourceError("collected response belongs to a different source endpoint")
    if evidence.get("http_status") != 200 or evidence.get("final_url") != url:
        raise SourceError("collected full-JD evidence must be an HTTP 200 without redirects")
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceError("collected response is not valid UTF-8") from exc


def validate_collected_observation(obs: dict) -> None:
    """离线校验完整 JD 收集包的同岗证据；不赋予手工 JSON 官方核验权。"""
    if not isinstance(obs, dict) or not obs.get("jd_raw") or jd_hash(obs["jd_raw"]) != obs.get("jd_hash"):
        raise SourceError("collected observation JD is missing or has a hash mismatch")
    channel, evidence = obs.get("source_channel", ""), obs.get("verification_evidence") or {}
    external_id = str(obs.get("external_id", ""))
    if channel == "ncss":
        expected = f"https://www.ncss.cn/student/jobs/{external_id}/detail.html"
        if not re.fullmatch(r"[A-Za-z0-9_-]+", external_id) or obs.get("source_url") != expected:
            raise SourceError("collected NCSS URL and external_id disagree")
        listing = evidence.get("listing") or (evidence.get("prior_evidence") or {}).get("listing")
        raw_list = json.loads(_read_collected_evidence(listing))
        list_url = parse.urlsplit(listing["requested_url"])
        if list_url.hostname != "www.ncss.cn" or list_url.path != parse.urlsplit(NCSS_API).path:
            raise SourceError("NCSS listing evidence belongs to a different endpoint")
        records = (raw_list.get("data") or {}).get("list", [])
        matching = [item for item in records if str(item.get("jobId", "")) == external_id]
        if len(matching) != 1 or matching[0].get("jobName") != obs.get("role_title") or matching[0].get("recName") != obs.get("company"):
            raise SourceError("collected NCSS listing identity does not match observation")
        text = _read_collected_evidence(evidence.get("detail"), expected)
        evaluated = _ncss_snapshot_state(obs, text)
        if evaluated["jd_raw"] != obs["jd_raw"] or evaluated["status"] != obs.get("verification_status"):
            raise SourceError("collected NCSS JD or claimed status disagrees with raw detail")
        if obs.get("location") != (evaluated["location"] or str(matching[0].get("areaCodeName", ""))):
            raise SourceError("collected NCSS location differs from raw detail/listing")
        if obs.get("official_url"):
            raise SourceError("NCSS platform evidence cannot assert an employer official URL")
    elif channel.startswith("greenhouse:"):
        board = _board_token(channel.split(":", 1)[1])
        canonical = _canonical_ats_url(obs.get("source_url", ""), board, external_id)
        if not canonical or not external_id.isdigit():
            raise SourceError("collected Greenhouse URL and external_id disagree")
        ats_evidence = evidence.get("ats")
        response = json.loads(_read_collected_evidence(ats_evidence))
        base = f"{GREENHOUSE_API}{board}/jobs"
        if ats_evidence.get("requested_url") not in {base + "?content=true", base + "/" + external_id}:
            raise SourceError("collected ATS evidence belongs to a different board or job")
        items = response.get("jobs", []) if "jobs" in response else [response]
        matching = [item for item in items if str(item.get("id", "")) == external_id]
        if len(matching) != 1:
            raise SourceError("collected ATS job ID missing or ambiguous in raw response")
        item = matching[0]
        if item.get("title") != obs.get("role_title") or extract_html(str(item.get("content", ""))) != obs["jd_raw"]:
            raise SourceError("collected ATS title or JD does not match raw response")
        company = str(item.get("company_name") or OFFICIAL_BOARDS.get(board, {}).get("company") or board)
        if company != obs.get("company") or _canonical_ats_url(str(item.get("absolute_url", "")), board, external_id) != canonical:
            raise SourceError("collected ATS company or application URL does not match raw response")
        if obs.get("location") != str((item.get("location") or {}).get("name", "")):
            raise SourceError("collected ATS location differs from raw response")
        if obs.get("verification_status") == "employer_verified":
            registry = OFFICIAL_BOARDS.get(board)
            if not registry or obs.get("official_url") != canonical:
                raise SourceError("collected ATS lacks configured employer-origin binding")
            text = _read_collected_evidence((evidence.get("employer_origin") or {}).get("employer_careers"), registry["careers"])
            parser = _TextExtractor(); parser.feed(text)
            if not any(_canonical_ats_url(link, board, external_id) == canonical for link in parser.links):
                raise SourceError("employer careers raw response does not link this exact ATS job")
            if _past_deadline(_date(item.get("application_deadline"))):
                raise SourceError("collected ATS application deadline has expired")
        elif obs.get("verification_status") not in {"unknown", "closed"} or obs.get("official_url"):
            raise SourceError("collected ATS has an unsupported or unproved status")
        elif obs.get("verification_status") == "closed" and not _past_deadline(_date(item.get("application_deadline"))):
            raise SourceError("collected ATS closed claim has no expired deadline evidence")
    else:
        raise SourceError("unsupported collected source; use unverified manual import")
    for key, expected in {"employment_type": _employment_type(obs["role_title"], obs["jd_raw"]), "work_mode": _work_mode(obs.get("location", ""), obs["jd_raw"]),
                          "source_verified": obs.get("verification_status") in {"employer_verified", "official_platform_live"}, "application_verified": obs.get("verification_status") == "employer_verified"}.items():
        if obs.get(key) != expected:
            raise SourceError(f"collected derived field disagrees with raw evidence: {key}")
