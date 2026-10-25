import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * T04: `src/lib/tutoringTypes.ts` is a field-for-field mirror of the two
 * Python DTO modules (`lemely/web/schemas_tutoring.py`,
 * `lemely/web/schemas_tutoring_admin.py`). The Python files are parsed as
 * text, every annotation is translated into the TypeScript it must become,
 * and the result is compared with the interfaces in the TS file:
 *
 *   - interface name = the Python class name without its `DTO` suffix, and a
 *     `…Lit` literal alias becomes a type alias without `Lit` (the repo's
 *     naming convention, `teacherTypes.ts` header);
 *   - the same field names, inherited ones included, with the TS interface
 *     extending the mirror of the Python base class;
 *   - the same type: `str` → `string`, `int`/`float` → `number`,
 *     `bool` → `boolean`, `X | None` → `X | null`, `list[X]` → `X[]`,
 *     `Literal[...]` → a string union, `dict[str, V]` → `Record<string, V>`;
 *   - a Python default ⇔ an optional (`?`) TS field.
 *
 * Source text only, against the repo root (not `web/`): both Python files
 * live outside the `web/` package. The Python side is counted against SPEC
 * §b.3 so a parser that silently skips classes cannot pass.
 */

const ROOT = join(import.meta.dirname, "..", "..", "..")
const read = (path: string): string => readFileSync(join(ROOT, path), "utf8")

const PYTHON_FILES = [
  "lemely/web/schemas_tutoring.py",
  "lemely/web/schemas_tutoring_admin.py",
] as const
const TS_FILE = "web/src/lib/tutoringTypes.ts"
/* The one TS alias with no Python `…Lit` twin: pydantic's own `JsonValue`,
 * the type of `ReportDetailDTO.snapshot`. */
const TS_ONLY_ALIASES = ["JsonValue"] as const

// ── Python source ───────────────────────────────────────────────────────────

interface PyField {
  name: string
  annotation: string
  hasDefault: boolean
}

interface PyClass {
  name: string
  base: string
  fields: PyField[]
}

interface PySource {
  classes: Map<string, PyClass>
  aliases: Map<string, string[]>
}

/** Bracket depth of `text`, ignoring brackets inside string literals. */
function depth(text: string): number {
  let level = 0
  let quote: string | null = null
  for (const char of text) {
    if (quote) {
      if (char === quote) quote = null
    } else if (char === '"' || char === "'") {
      quote = char
    } else if (char === "[" || char === "(") {
      level += 1
    } else if (char === "]" || char === ")") {
      level -= 1
    }
  }
  return level
}

/** `line` without a trailing `# comment` (a `#` inside a string is kept). */
function stripComment(line: string): string {
  let quote: string | null = null
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index]
    if (quote) {
      if (char === quote) quote = null
    } else if (char === '"' || char === "'") {
      quote = char
    } else if (char === "#") {
      return line.slice(0, index)
    }
  }
  return line
}

/** Split `text` on `separator` where it sits outside brackets and strings. */
function splitTopLevel(text: string, separator: string): string[] {
  const parts: string[] = []
  let start = 0
  let level = 0
  let quote: string | null = null
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    if (quote) {
      if (char === quote) quote = null
    } else if (char === '"' || char === "'") {
      quote = char
    } else if (char === "[" || char === "(") {
      level += 1
    } else if (char === "]" || char === ")") {
      level -= 1
    } else if (char === separator && level === 0) {
      parts.push(text.slice(start, index))
      start = index + 1
    }
  }
  parts.push(text.slice(start))
  return parts
}

function parsePython(source: string): PySource {
  const lines = source.split("\n")
  const classes = new Map<string, PyClass>()
  const aliases = new Map<string, string[]>()
  let current: PyClass | null = null
  let inDocstring = false
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const trimmed = line.trim()
    if (inDocstring) {
      if (trimmed.includes('"""')) inDocstring = false
      continue
    }
    if (trimmed.startsWith('"""')) {
      inDocstring = (trimmed.match(/"""/g) ?? []).length === 1
      continue
    }
    const classLine = /^class (\w+)\((\w+)\):/.exec(line)
    if (classLine) {
      current = { name: classLine[1], base: classLine[2], fields: [] }
      classes.set(current.name, current)
      continue
    }
    const aliasLine = /^(\w+Lit) = (.*)$/.exec(line)
    if (aliasLine) {
      let statement = stripComment(aliasLine[2])
      while (depth(statement) > 0 && index + 1 < lines.length) {
        index += 1
        statement += ` ${stripComment(lines[index])}`
      }
      aliases.set(
        aliasLine[1],
        [...statement.matchAll(/"([^"]*)"/g)].map((match) => match[1]),
      )
      current = null
      continue
    }
    if (trimmed !== "" && !line.startsWith(" ")) {
      current = null
      continue
    }
    const fieldLine = /^ {4}(\w+): (.*)$/.exec(line)
    if (current && fieldLine) {
      let statement = stripComment(fieldLine[2])
      while (depth(statement) > 0 && index + 1 < lines.length) {
        index += 1
        statement += ` ${stripComment(lines[index])}`
      }
      const [annotation, ...rest] = splitTopLevel(statement, "=")
      current.fields.push({
        name: fieldLine[1],
        annotation: annotation.trim(),
        hasDefault: rest.length > 0,
      })
    }
  }
  return { classes, aliases }
}

// ── Python annotation → TypeScript type ────────────────────────────────────

type TypeNode =
  | { kind: "name"; name: string }
  | { kind: "string"; value: string }
  | { kind: "generic"; name: string; args: TypeNode[] }
  | { kind: "union"; members: TypeNode[] }

function tokenize(text: string): string[] {
  const token = /\s*("[^"]*"|'[^']*'|\w+|[[\](),|])/y
  const tokens: string[] = []
  let index = 0
  while (text.slice(index).trim() !== "") {
    token.lastIndex = index
    const match = token.exec(text)
    if (!match) throw new Error(`cannot read annotation ${JSON.stringify(text)} at ${index}`)
    tokens.push(match[1])
    index = token.lastIndex
  }
  return tokens
}

function parseAnnotation(text: string): TypeNode {
  const tokens = tokenize(text)
  let position = 0
  const parsePrimary = (): TypeNode => {
    const token = tokens[position]
    position += 1
    if (token === undefined) throw new Error(`annotation ends early: ${text}`)
    if (token === "(") {
      // A formatter wraps a long annotation in parentheses; they carry no type.
      const inner = parseUnion()
      if (tokens[position] !== ")") throw new Error(`unclosed ( in ${text}`)
      position += 1
      return inner
    }
    if (token.startsWith('"') || token.startsWith("'")) {
      return { kind: "string", value: token.slice(1, -1) }
    }
    if (tokens[position] !== "[") return { kind: "name", name: token }
    position += 1
    const args = [parseUnion()]
    while (tokens[position] === ",") {
      position += 1
      if (tokens[position] === "]") break // a formatter's trailing comma
      args.push(parseUnion())
    }
    if (tokens[position] !== "]") throw new Error(`unclosed [ in ${text}`)
    position += 1
    return { kind: "generic", name: token, args }
  }
  const parseUnion = (): TypeNode => {
    const members = [parsePrimary()]
    while (tokens[position] === "|") {
      position += 1
      members.push(parsePrimary())
    }
    return members.length === 1 ? members[0] : { kind: "union", members }
  }
  const node = parseUnion()
  if (position !== tokens.length) throw new Error(`trailing tokens in ${text}`)
  return node
}

const SCALARS: Record<string, string> = {
  str: "string",
  int: "number",
  float: "number",
  bool: "boolean",
  None: "null",
  JsonValue: "JsonValue",
}

function renderName(name: string): string {
  if (name in SCALARS) return SCALARS[name]
  if (name.endsWith("DTO") || name.endsWith("Lit")) return name.slice(0, -3)
  throw new Error(`no TypeScript mirror for Python type ${name}`)
}

function isUnionLike(node: TypeNode): boolean {
  return (
    node.kind === "union" ||
    (node.kind === "generic" && node.name === "Literal" && node.args.length > 1)
  )
}

function render(node: TypeNode): string {
  switch (node.kind) {
    case "string":
      return JSON.stringify(node.value)
    case "name":
      return renderName(node.name)
    case "union":
      return node.members.map(render).join(" | ")
    case "generic": {
      if (node.name === "Literal") return node.args.map(render).join(" | ")
      if (node.name === "list") {
        const element = render(node.args[0])
        return isUnionLike(node.args[0]) ? `(${element})[]` : `${element}[]`
      }
      if (node.name === "dict") return `Record<${render(node.args[0])}, ${render(node.args[1])}>`
      throw new Error(`no TypeScript mirror for Python generic ${node.name}`)
    }
  }
}

const toTs = (annotation: string): string => render(parseAnnotation(annotation))
const stripSuffix = (name: string): string => name.slice(0, -3)

// ── TypeScript source ───────────────────────────────────────────────────────

interface TsField {
  name: string
  type: string
  optional: boolean
}

interface TsInterface {
  name: string
  extends: string[]
  fields: TsField[]
}

const squash = (text: string): string =>
  text.replace(/\s+/g, " ").trim().replace(/^\| /, "")

function parseTs(source: string): {
  interfaces: Map<string, TsInterface>
  aliases: Map<string, string>
} {
  const lines = source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((line) => line.replace(/\/\/.*$/, ""))
  const interfaces = new Map<string, TsInterface>()
  const aliases = new Map<string, string>()
  let current: TsInterface | null = null
  let alias: string | null = null
  for (const line of lines) {
    const head = /^export interface (\w+)(?: extends ([\w, ]+))? \{$/.exec(line)
    if (head) {
      current = {
        name: head[1],
        extends: head[2] ? head[2].split(",").map((name) => name.trim()) : [],
        fields: [],
      }
      interfaces.set(current.name, current)
      alias = null
      continue
    }
    const typeLine = /^export type (\w+) =(.*)$/.exec(line)
    if (typeLine) {
      alias = typeLine[1]
      aliases.set(alias, typeLine[2])
      current = null
      continue
    }
    if (alias && /^\s+\S/.test(line)) {
      aliases.set(alias, `${aliases.get(alias) ?? ""} ${line}`)
      continue
    }
    alias = null
    if (line.startsWith("}")) {
      current = null
      continue
    }
    if (!current) continue
    const field = /^ {2}(\w+)(\?)?: (.*)$/.exec(line)
    if (field) {
      current.fields.push({ name: field[1], type: field[3], optional: field[2] === "?" })
    } else if (line.trim() !== "" && current.fields.length > 0) {
      current.fields[current.fields.length - 1].type += ` ${line}`
    }
  }
  for (const value of interfaces.values()) {
    for (const field of value.fields) field.type = squash(field.type)
  }
  for (const [name, value] of aliases) aliases.set(name, squash(value))
  return { interfaces, aliases }
}

// ── SPEC §b.3 count (non-vacuity) ───────────────────────────────────────────

function specDtoCount(spec: string): number {
  const start = spec.indexOf("### b.3 DTOs")
  const section = spec.slice(start, spec.indexOf("### b.4 ", start))
  const code = /```python\n([\s\S]*?)```/.exec(section)
  if (!code) throw new Error("SPEC §b.3 has no python block")
  const blockClasses = code[1].match(/^class \w+\(/gm) ?? []
  const adminStart = section.indexOf("Admin DTOs (`schemas_tutoring_admin.py`):")
  const adminParagraph = section.slice(adminStart, section.indexOf("**", adminStart))
  const adminNames = new Set([...adminParagraph.matchAll(/`(\w+DTO)`/g)].map((m) => m[1]))
  return blockClasses.length + adminNames.size
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe("tutoringTypes.ts mirrors the Python tutoring DTOs", () => {
  const pythonSources = PYTHON_FILES.map((path) => read(path))
  const python: PySource = { classes: new Map(), aliases: new Map() }
  for (const source of pythonSources) {
    const parsed = parsePython(source)
    for (const [name, value] of parsed.classes) python.classes.set(name, value)
    for (const [name, value] of parsed.aliases) python.aliases.set(name, value)
  }
  const ts = parseTs(read(TS_FILE))

  const pyFields = (name: string): PyField[] => {
    const cls = python.classes.get(name)
    if (!cls) throw new Error(`Python base class ${name} is not in the tutoring modules`)
    const inherited = cls.base === "ApiModel" ? [] : pyFields(cls.base)
    return [...inherited, ...cls.fields]
  }
  const tsFields = (name: string): TsField[] => {
    const value = ts.interfaces.get(name)
    if (!value) throw new Error(`TS interface ${name} is missing`)
    return [...value.extends.flatMap(tsFields), ...value.fields]
  }

  it("parses every Python DTO class, at least as many as SPEC §b.3 names", () => {
    const classLines = pythonSources.flatMap((source) => source.match(/^class \w+\(/gm) ?? [])
    expect(python.classes.size).toBe(classLines.length)
    expect(python.classes.size).toBeGreaterThanOrEqual(specDtoCount(read("docs/tutoring/SPEC.md")))
  })

  it("every Python DTO class has a TS interface with the same field names", () => {
    const expected = [...python.classes.keys()].map(stripSuffix).sort()
    expect([...ts.interfaces.keys()].sort()).toEqual(expected)
    for (const name of python.classes.keys()) {
      const pyNames = pyFields(name).map((field) => field.name).sort()
      const tsNames = tsFields(stripSuffix(name)).map((field) => field.name).sort()
      expect({ [name]: tsNames }).toEqual({ [name]: pyNames })
    }
  })

  it("each TS field has the type and optionality its Python field declares", () => {
    let compared = 0
    for (const name of python.classes.keys()) {
      const mirror = new Map(tsFields(stripSuffix(name)).map((field) => [field.name, field]))
      for (const field of pyFields(name)) {
        const tsField = mirror.get(field.name)
        expect(tsField, `${name}.${field.name}`).toBeDefined()
        expect({ [`${name}.${field.name}`]: tsField?.type }).toEqual({
          [`${name}.${field.name}`]: toTs(field.annotation),
        })
        expect({ [`${name}.${field.name}?`]: tsField?.optional }).toEqual({
          [`${name}.${field.name}?`]: field.hasDefault,
        })
        compared += 1
      }
    }
    expect(compared).toBeGreaterThan(python.classes.size)
  })

  it("each TS interface extends the TS mirror of its Python base class", () => {
    for (const cls of python.classes.values()) {
      const expected = cls.base === "ApiModel" ? [] : [stripSuffix(cls.base)]
      expect({ [cls.name]: ts.interfaces.get(stripSuffix(cls.name))?.extends }).toEqual({
        [cls.name]: expected,
      })
    }
  })

  it("each Python Literal alias has a TS union alias with the same values in order", () => {
    expect(python.aliases.size).toBeGreaterThanOrEqual(4)
    const expected = [...python.aliases.keys()].map(stripSuffix)
    expect([...ts.aliases.keys()].sort()).toEqual([...expected, ...TS_ONLY_ALIASES].sort())
    for (const [name, values] of python.aliases) {
      expect({ [name]: ts.aliases.get(stripSuffix(name)) }).toEqual({
        [name]: values.map((value) => JSON.stringify(value)).join(" | "),
      })
    }
  })
})
