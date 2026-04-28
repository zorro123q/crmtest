"""
Small CSV/XLSX helpers for CRM table imports.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from typing import Iterable
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape


XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass(frozen=True)
class ImportColumn:
    key: str
    title: str
    required: bool = False
    sample: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportRow:
    row_number: int
    values: dict[str, str]


LEAD_IMPORT_COLUMNS = (
    ImportColumn("serial_no", "序号", False, "1", ("编号", "序列号")),
    ImportColumn("business_owner", "商务名称", False, "张三", ("商务负责人", "负责人", "销售负责人")),
    ImportColumn("unit_name", "单位名称", True, "示例科技有限公司", ("客户名称", "公司名称", "公司", "name", "company")),
    ImportColumn("industry_category", "行业类别", False, "金融"),
    ImportColumn("customer_type", "新老客户", False, "新客户"),
    ImportColumn("opportunity_level", "商机等级", False, "A"),
    ImportColumn("requirement_desc", "需求描述", False, "需要智能外呼和质检能力"),
    ImportColumn("budget_amount", "预算额度", False, "100万"),
    ImportColumn("lead_source", "线索来源", False, "展会"),
    ImportColumn("purchased_related_products", "是否采购过相关产品", False, "否"),
    ImportColumn("first_review_pass", "初审是否通过", False, "是", ("第一次初审是否通过",)),
    ImportColumn("visit_key_time", "拜访客户关键人时间", False, "2026-04-27"),
    ImportColumn("decision_chain_info", "关键决策链信息", False, "业务负责人和采购负责人共同评估"),
    ImportColumn("cooperation_intent", "需求及合作意向", False, "高"),
    ImportColumn("next_visit_plan", "下次拜访计划", False, "约方案评审会"),
    ImportColumn("second_review_pass", "初审是否通过", False, "", ("第二次初审是否通过",)),
    ImportColumn("cooperation_scheme_status", "合作方案交流情况", False, "方案沟通中"),
    ImportColumn("key_person_approved", "关键人是否认可", False, ""),
    ImportColumn("next_step_plan", "下步计划", False, "补充预算测算"),
    ImportColumn("third_review_pass", "初审是否通过", False, "", ("第三次初审是否通过",)),
    ImportColumn("status", "状态", False, "", ("status",)),
    ImportColumn("email", "邮箱", False, "lead@example.com", ("email",)),
    ImportColumn("phone", "电话", False, "13800000000", ("phone",)),
)


OPPORTUNITY_IMPORT_COLUMNS = (
    ImportColumn("serial_no", "序号", False, "1", ("编号", "序列号")),
    ImportColumn("owner_name_display", "商务负责人", False, "张三", ("商机负责人", "负责人", "销售负责人")),
    ImportColumn("customer_name", "（客户）名称", True, "示例科技有限公司", ("客户名称", "公司名称", "公司", "customer", "company")),
    ImportColumn("customer_type", "新老客户", False, "新客户"),
    ImportColumn("requirement_desc", "需求描述（需要详细描述）", False, "需要智能外呼和质检能力", ("需求描述", "需求详情")),
    ImportColumn("product_name", "涉及产品", True, "智能外呼平台", ("产品名称", "product")),
    ImportColumn("amount", "预算情况", False, "1000000", ("预算金额", "金额", "budget", "amount")),
    ImportColumn("estimated_cycle", "预估成交周期", False, "3个月", ("预计成交周期",)),
    ImportColumn("opportunity_level", "商机等级", False, "A"),
    ImportColumn("project_date", "立项日期", False, "2026-04-27"),
    ImportColumn("project_members", "项目组成员", False, "张三、李四"),
    ImportColumn("solution_communication", "解决方案沟通情况（需要填写沟通情况及结果）", False, "方案沟通中", ("解决方案沟通情况", "方案沟通情况")),
    ImportColumn("poc_status", "POC测试情况", False, "待启动", ("POC 测试情况",)),
    ImportColumn("key_person_approved", "关键人是否对方案认可", False, "待确认"),
    ImportColumn("bid_probability", "商机B卡中的概率", False, "B", ("商机B卡中标的概率", "商机B卡中标概率", "B卡中标概率")),
    ImportColumn("contract_negotiation", "合同谈判情况", False, ""),
    ImportColumn("project_type", "项目类型", False, "SaaS"),
    ImportColumn("contract_signed", "是否已签订合同", False, "否"),
    ImportColumn("handoff_completed", "是否已完成项目交底", False, "否", ("是否完成项目的交底", "是否完成交底")),
    ImportColumn("stage", "阶段", False, "", ("商机阶段", "stage")),
    ImportColumn("status", "状态", False, "", ("status",)),
)


def parse_import_table(filename: str, content: bytes, columns: Iterable[ImportColumn]) -> list[ImportRow]:
    if not content:
        raise ValueError("上传文件为空")

    lower_name = (filename or "").lower()
    if lower_name.endswith(".csv"):
        return _parse_csv(content, columns)
    if lower_name.endswith(".xlsx"):
        return _parse_xlsx(content, columns)
    raise ValueError("仅支持 .xlsx 或 .csv 文件")


def build_template_file(columns: Iterable[ImportColumn], file_format: str) -> tuple[bytes, str, str]:
    normalized = str(file_format or "xlsx").lower()
    if normalized == "csv":
        return (
            _build_csv_template(columns),
            "text/csv; charset=utf-8",
            "csv",
        )
    if normalized == "xlsx":
        return (
            _build_xlsx_template(columns),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    raise ValueError("模板格式仅支持 xlsx 或 csv")


def normalize_header(value: str) -> str:
    return re.sub(r"[\s_　:：/\\-]+", "", str(value or "").strip().lower())


def empty_to_none(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def import_error_message(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        detail = errors()
        if detail:
            first = detail[0]
            location = ".".join(str(part) for part in first.get("loc", ()))
            message = first.get("msg") or str(exc)
            return f"{location}: {message}" if location else message
    return str(exc)


def _parse_csv(content: bytes, columns: Iterable[ImportColumn]) -> list[ImportRow]:
    column_list = list(columns)
    text = _decode_csv(content)
    reader = csv.reader(io.StringIO(text))
    rows_raw = list(reader)

    if not rows_raw:
        raise ValueError("文件内容为空")

    headers = rows_raw[0]
    rows: list[ImportRow] = []

    for index, values in enumerate(rows_raw[1:], start=2):
        mapped = _map_row_by_headers(headers, values, column_list)
        if _is_blank_row(mapped) or _is_template_sample_row(mapped, column_list):
            continue
        rows.append(ImportRow(row_number=index, values=mapped))
    return rows


def _parse_xlsx(content: bytes, columns: Iterable[ImportColumn]) -> list[ImportRow]:
    column_list = list(columns)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as workbook:
            shared_strings = _read_shared_strings(workbook)
            sheet_path = _first_sheet_path(workbook)
            sheet_xml = workbook.read(sheet_path)
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ValueError("无法读取 xlsx 文件，请使用模板重新填写后上传") from exc

    root = ET.fromstring(sheet_xml)
    namespace = {"x": XLSX_MAIN_NS}
    sheet_data = root.find("x:sheetData", namespace)
    if sheet_data is None:
        raise ValueError("文件中没有可导入的数据")

    raw_rows: list[tuple[int, list[str]]] = []
    for row in sheet_data.findall("x:row", namespace):
        row_number = int(row.attrib.get("r", len(raw_rows) + 1))
        values_by_column: dict[int, str] = {}
        for cell in row.findall("x:c", namespace):
            column_index = _cell_column_index(cell.attrib.get("r", ""))
            if column_index < 1:
                continue
            values_by_column[column_index] = _cell_text(cell, shared_strings)

        if not values_by_column:
            continue
        max_column = max(values_by_column)
        raw_rows.append((row_number, [values_by_column.get(i, "") for i in range(1, max_column + 1)]))

    header_row = next(((row_number, values) for row_number, values in raw_rows if any(v.strip() for v in values)), None)
    if header_row is None:
        raise ValueError("文件缺少表头")

    header_number, headers = header_row
    rows: list[ImportRow] = []

    for row_number, values in raw_rows:
        if row_number <= header_number:
            continue
        mapped = _map_row_by_headers(headers, values, column_list)
        if _is_blank_row(mapped) or _is_template_sample_row(mapped, column_list):
            continue
        rows.append(ImportRow(row_number=row_number, values=mapped))
    return rows


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别 CSV 编码，请另存为 UTF-8 后上传")


def _column_alias_map(columns: Iterable[ImportColumn]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for column in columns:
        labels = (column.key, column.title, *column.aliases)
        for label in labels:
            mapping[normalize_header(label)] = column.key
    return mapping


def _build_column_alias_sets(columns: list[ImportColumn]) -> list[set[str]]:
    """
    为每个 ImportColumn 构建标准化别名集合，包含：
    - key
    - title
    - 所有 aliases
    用于重复表头匹配。
    """
    result = []
    for column in columns:
        aliases = set()
        # 添加 key
        aliases.add(normalize_header(column.key))
        # 添加 title
        aliases.add(normalize_header(column.title))
        # 添加所有 aliases
        for alias in column.aliases:
            aliases.add(normalize_header(alias))
        result.append(aliases)
    return result


def _map_row_by_headers(headers: list[str], values: list[str], columns: list[ImportColumn]) -> dict[str, str]:
    """
    按 headers 顺序 + columns 定义顺序映射一行数据。
    支持重复表头：对于同名列（如多个"初审是否通过"），
    按 columns 中出现顺序依次匹配下一个同名列。
    """
    column_list = columns
    alias_sets = _build_column_alias_sets(column_list)

    # 记录每个列已经被匹配过的次数（用于处理重复表头）
    # matched_count[i] 表示 column_list[i] 已经被消费了几次
    matched_count = [0] * len(column_list)

    mapped: dict[str, str] = {}

    for header_index, header in enumerate(headers):
        header_normalized = normalize_header(header)
        if not header_normalized:
            continue

        value = values[header_index] if header_index < len(values) else ""

        # 找到所有能匹配这个 header 的列
        matching_cols = []
        for col_index, alias_set in enumerate(alias_sets):
            if header_normalized in alias_set:
                matching_cols.append(col_index)

        if not matching_cols:
            continue

        # 选择第一个未消费的匹配列
        # 这样对于重复表头，会按 columns 顺序依次消费
        for col_index in matching_cols:
            if matched_count[col_index] == 0:
                matched_count[col_index] = 1
                key = column_list[col_index].key
                mapped[key] = str(value or "").strip()
                break

    return mapped


def _map_row(raw_row: dict[str, str | None], alias_map: dict[str, str]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for header, value in raw_row.items():
        key = alias_map.get(normalize_header(header))
        if key:
            mapped[key] = str(value or "").strip()
    return mapped


def _is_blank_row(row: dict[str, str]) -> bool:
    return not any(str(value or "").strip() for value in row.values())


def _is_template_sample_row(row: dict[str, str], columns: Iterable[ImportColumn]) -> bool:
    samples = {column.key: column.sample for column in columns if column.sample}
    if not samples:
        return False
    populated = {key: value for key, value in row.items() if str(value or "").strip()}
    if not populated:
        return False
    return all(str(populated.get(key, "")).strip() == str(sample).strip() for key, sample in samples.items() if sample)


def _read_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    except KeyError:
        return []

    namespace = {"x": XLSX_MAIN_NS}
    values: list[str] = []
    for item in root.findall("x:si", namespace):
        parts = [node.text or "" for node in item.findall(".//x:t", namespace)]
        values.append("".join(parts))
    return values


def _first_sheet_path(workbook: zipfile.ZipFile) -> str:
    workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
    namespace = {"x": XLSX_MAIN_NS, "r": XLSX_REL_NS}
    first_sheet = workbook_root.find("x:sheets/x:sheet", namespace)
    if first_sheet is None:
        return "xl/worksheets/sheet1.xml"

    rel_id = first_sheet.attrib.get(f"{{{XLSX_REL_NS}}}id")
    if not rel_id:
        return "xl/worksheets/sheet1.xml"

    rels_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    for relationship in rels_root.findall(f"{{{PACKAGE_REL_NS}}}Relationship"):
        if relationship.attrib.get("Id") == rel_id:
            target = relationship.attrib.get("Target", "worksheets/sheet1.xml")
            return "xl/" + target.lstrip("/")
    return "xl/worksheets/sheet1.xml"


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    namespace = {"x": XLSX_MAIN_NS}

    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//x:t", namespace)).strip()

    value_node = cell.find("x:v", namespace)
    if value_node is None or value_node.text is None:
        return ""

    raw_value = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)].strip()
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return "是" if raw_value == "1" else "否"
    return raw_value.strip()


def _cell_column_index(cell_reference: str) -> int:
    letters = re.sub(r"[^A-Za-z]", "", cell_reference or "")
    index = 0
    for letter in letters.upper():
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index


def _column_letter(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _build_csv_template(columns: Iterable[ImportColumn]) -> bytes:
    column_list = list(columns)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([column.title for column in column_list])
    writer.writerow([column.sample for column in column_list])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _build_xlsx_template(columns: Iterable[ImportColumn]) -> bytes:
    column_list = list(columns)
    rows = [
        [column.title for column in column_list],
        [column.sample for column in column_list],
    ]
    sheet_rows = []
    for row_index, row_values in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row_values, start=1):
            ref = f"{_column_letter(column_index)}{row_index}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value or ""))}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    worksheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{XLSX_MAIN_NS}" xmlns:r="{XLSX_REL_NS}">'
        "<sheetViews><sheetView workbookViewId=\"0\"><pane ySplit=\"1\" topLeftCell=\"A2\" "
        "activePane=\"bottomLeft\" state=\"frozen\"/></sheetView></sheetViews>"
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        "</worksheet>"
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            "</Types>",
        )
        workbook.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PACKAGE_REL_NS}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>",
        )
        workbook.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{XLSX_MAIN_NS}" xmlns:r="{XLSX_REL_NS}">'
            '<sheets><sheet name="导入模板" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PACKAGE_REL_NS}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        workbook.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
        workbook.writestr(
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>CRM 导入模板</dc:title></cp:coreProperties>',
        )
        workbook.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            "<Application>SalesPilot CRM</Application></Properties>",
        )

    return output.getvalue()
