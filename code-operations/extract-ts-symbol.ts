#!/usr/bin/env tsx

import fs from "node:fs";
import path from "node:path";
import { Command, Option } from "commander";
import ts from "typescript";

type Mode = "copy" | "cut";

type CliOptions = {
  mode: Mode;
  copy?: boolean;
  cut?: boolean;
  dryRun?: boolean;
  overwrite?: boolean;
  backup?: boolean;
  print?: boolean;
  list?: boolean;
  keepComments?: boolean;
};

type Match = {
  name: string;
  node: ts.Node;
};

type Removal = {
  start: number;
  end: number;
  reason: string;
};

const program = new Command();

program
  .name("symbol-extract")
  .description(
    "Extract a TypeScript symbol from one source file by dot path, optionally cutting it from the original file.",
  )
  .version("1.0.0")
  .argument("<input>", "input .ts/.tsx/.js/.jsx file")
  .argument("<symbol>", "dot-delimited symbol path, e.g. Foo.bar.inner")
  .argument("<output>", "output file for extracted symbol")
  .addOption(
    new Option("-m, --mode <mode>", "copy or cut")
      .choices(["copy", "cut"])
      .default("copy"),
  )
  .option("--copy", "copy the symbol into the output file and leave input unchanged")
  .option("--cut", "copy the symbol into the output file and remove it from the input file")
  .option("--dry-run", "print what would happen without writing files")
  .option("--overwrite", "allow overwriting the output file")
  .option("--backup", "when cutting, write <input>.bak before modifying the input file")
  .option("--print", "also print extracted text to stdout")
  .option("--list", "list visible symbols near the matched path if the symbol cannot be found")
  .option("--keep-comments", "preserve comments when printing extracted AST")
  .parse();

const [inputFile, symbolPath, outputFile] = program.args as [string, string, string];
const options = program.opts<CliOptions>();

main();

function main(): void {
  const mode = resolveMode(options);

  if (!fs.existsSync(inputFile)) {
    fail(`Input file does not exist: ${inputFile}`);
  }

  if (fs.existsSync(outputFile) && !options.overwrite && !options.dryRun) {
    fail(`Output file already exists: ${outputFile}. Use --overwrite to replace it.`);
  }

  const sourceText = fs.readFileSync(inputFile, "utf8");
  const sourceFile = parseSourceFile(inputFile, sourceText);

  const found = findByDotPath(sourceFile, symbolPath);

  if (!found) {
    console.error(`Could not find symbol path: ${symbolPath}`);

    if (options.list) {
      console.error("");
      console.error("Top-level symbols:");
      for (const name of directNamedChildren(sourceFile).map(m => m.name)) {
        console.error(`  - ${name}`);
      }
    }

    process.exit(2);
  }

  const extractedText = extractText(found, sourceFile, {
    keepComments: Boolean(options.keepComments),
  });

  const banner = `// Extracted from ${path.basename(inputFile)} as "${symbolPath}"\n\n`;
  const outputText = banner + extractedText.trimEnd() + "\n";

  if (options.print || options.dryRun) {
    console.log(outputText);
  }

  if (options.dryRun) {
    console.error(`[dry-run] Would write extracted symbol to: ${outputFile}`);

    if (mode === "cut") {
      const removal = computeRemoval(found, sourceFile, sourceText);
      console.error(
        `[dry-run] Would remove ${removal.end - removal.start} chars from input: ` +
          `${inputFile} (${removal.reason})`,
      );
    }

    return;
  }

  fs.writeFileSync(outputFile, outputText, "utf8");

  if (mode === "cut") {
    const removal = computeRemoval(found, sourceFile, sourceText);

    if (options.backup) {
      fs.writeFileSync(`${inputFile}.bak`, sourceText, "utf8");
    }

    const updatedSource =
      sourceText.slice(0, removal.start) +
      sourceText.slice(removal.end);

    fs.writeFileSync(inputFile, updatedSource, "utf8");

    console.error(`Cut "${symbolPath}" to ${outputFile}`);
    console.error(`Removed from ${inputFile}: ${removal.reason}`);
  } else {
    console.error(`Copied "${symbolPath}" to ${outputFile}`);
    console.error(`Input file unchanged: ${inputFile}`);
  }
}

function resolveMode(options: CliOptions): Mode {
  if (options.copy && options.cut) {
    fail("Use only one of --copy or --cut.");
  }

  if (options.copy) return "copy";
  if (options.cut) return "cut";

  return options.mode;
}

function parseSourceFile(fileName: string, text: string): ts.SourceFile {
  const scriptKind =
    fileName.endsWith(".tsx") ? ts.ScriptKind.TSX :
    fileName.endsWith(".jsx") ? ts.ScriptKind.JSX :
    fileName.endsWith(".js") ? ts.ScriptKind.JS :
    ts.ScriptKind.TS;

  return ts.createSourceFile(
    fileName,
    text,
    ts.ScriptTarget.Latest,
    true,
    scriptKind,
  );
}

function findByDotPath(root: ts.Node, dotPath: string): ts.Node | undefined {
  const parts = dotPath.split(".").map(p => p.trim()).filter(Boolean);
  if (parts.length === 0) return undefined;

  let current: ts.Node = root;

  for (const part of parts) {
    const matches = directNamedChildren(current).filter(c => c.name === part);

    if (matches.length === 0) {
      return undefined;
    }

    if (matches.length > 1) {
      const locations = matches.map(m => locationOf(m.node));
      throw new Error(
        `Ambiguous symbol segment "${part}". Matches:\n` +
          locations.map(loc => `  - ${part} at ${loc}`).join("\n"),
      );
    }

    current = matches[0].node;
  }

  return current;
}

function directNamedChildren(root: ts.Node): Match[] {
  const searchRoot = childSearchRoot(root);
  const out: Match[] = [];

  const visit = (node: ts.Node): void => {
    const name = nameOfNode(node);

    if (name) {
      out.push({ name, node });
      return;
    }

    // Keep descending through anonymous containers so local declarations inside
    // blocks and expressions can be found.
    node.forEachChild(visit);
  };

  searchRoot.forEachChild(visit);
  return out;
}

function childSearchRoot(node: ts.Node): ts.Node {
  if (ts.isSourceFile(node)) return node;

  if (ts.isFunctionDeclaration(node) && node.body) return node.body;
  if (ts.isFunctionExpression(node) && node.body) return node.body;
  if (ts.isArrowFunction(node) && ts.isBlock(node.body)) return node.body;

  if (ts.isClassDeclaration(node) || ts.isClassExpression(node)) return node;

  if (ts.isMethodDeclaration(node) && node.body) return node.body;
  if (ts.isConstructorDeclaration(node) && node.body) return node.body;
  if (ts.isGetAccessorDeclaration(node) && node.body) return node.body;
  if (ts.isSetAccessorDeclaration(node) && node.body) return node.body;

  if (ts.isVariableDeclaration(node) && node.initializer) return node.initializer;

  if (ts.isPropertyDeclaration(node) && node.initializer) return node.initializer;

  if (ts.isPropertyAssignment(node)) return node.initializer;

  if (ts.isModuleDeclaration(node) && node.body) return node.body;

  return node;
}

function nameOfNode(node: ts.Node): string | undefined {
  if (
    ts.isFunctionDeclaration(node) ||
    ts.isClassDeclaration(node) ||
    ts.isInterfaceDeclaration(node) ||
    ts.isEnumDeclaration(node) ||
    ts.isTypeAliasDeclaration(node) ||
    ts.isModuleDeclaration(node)
  ) {
    return node.name?.text;
  }

  if (
    ts.isMethodDeclaration(node) ||
    ts.isPropertyDeclaration(node) ||
    ts.isGetAccessorDeclaration(node) ||
    ts.isSetAccessorDeclaration(node)
  ) {
    return propertyNameText(node.name);
  }

  if (ts.isConstructorDeclaration(node)) {
    return "constructor";
  }

  if (ts.isVariableDeclaration(node)) {
    return bindingNameText(node.name);
  }

  if (ts.isParameter(node)) {
    return bindingNameText(node.name);
  }

  if (ts.isPropertyAssignment(node)) {
    return propertyNameText(node.name);
  }

  if (ts.isShorthandPropertyAssignment(node)) {
    return node.name.text;
  }

  if (ts.isImportSpecifier(node) || ts.isExportSpecifier(node)) {
    return node.name.text;
  }

  return undefined;
}

function propertyNameText(name: ts.PropertyName): string | undefined {
  if (ts.isIdentifier(name)) return name.text;
  if (ts.isStringLiteral(name) || ts.isNumericLiteral(name)) return name.text;
  return undefined;
}

function bindingNameText(name: ts.BindingName): string | undefined {
  if (ts.isIdentifier(name)) return name.text;
  return undefined;
}

function extractText(
  node: ts.Node,
  sourceFile: ts.SourceFile,
  config: { keepComments: boolean },
): string {
  const printable = printableNode(node, sourceFile);

  const printer = ts.createPrinter({
    newLine: ts.NewLineKind.LineFeed,
    removeComments: !config.keepComments,
  });

  return printer.printNode(ts.EmitHint.Unspecified, printable, sourceFile);
}

function printableNode(node: ts.Node, sourceFile: ts.SourceFile): ts.Node {
  if (ts.isVariableDeclaration(node)) {
    return makeSingleVariableStatement(node);
  }

  if (ts.isParameter(node)) {
    return node;
  }

  return node;
}

function makeSingleVariableStatement(node: ts.VariableDeclaration): ts.VariableStatement {
  const list = node.parent;

  if (!ts.isVariableDeclarationList(list)) {
    throw new Error("VariableDeclaration parent was not a VariableDeclarationList.");
  }

  const parentStatement = list.parent;

  const modifiers =
    ts.isVariableStatement(parentStatement)
      ? ts.getModifiers(parentStatement)
      : undefined;

  const clonedDeclaration = ts.factory.createVariableDeclaration(
    node.name,
    node.exclamationToken,
    node.type,
    node.initializer,
  );

  return ts.factory.createVariableStatement(
    modifiers,
    ts.factory.createVariableDeclarationList([clonedDeclaration], list.flags),
  );
}

function computeRemoval(
  node: ts.Node,
  sourceFile: ts.SourceFile,
  sourceText: string,
): Removal {
  if (ts.isVariableDeclaration(node)) {
    return computeVariableDeclarationRemoval(node, sourceFile, sourceText);
  }

  if (ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node)) {
    return computeCommaListRemoval(node, sourceText, "object property");
  }

  if (
    ts.isMethodDeclaration(node) ||
    ts.isPropertyDeclaration(node) ||
    ts.isGetAccessorDeclaration(node) ||
    ts.isSetAccessorDeclaration(node) ||
    ts.isConstructorDeclaration(node)
  ) {
    return computeClassMemberRemoval(node, sourceText);
  }

  const start = startIncludingLeadingTrivia(node, sourceFile);
  const end = endIncludingTrailingNewline(node, sourceText);

  return {
    start,
    end,
    reason: ts.SyntaxKind[node.kind],
  };
}

function computeVariableDeclarationRemoval(
  node: ts.VariableDeclaration,
  sourceFile: ts.SourceFile,
  sourceText: string,
): Removal {
  const list = node.parent;

  if (!ts.isVariableDeclarationList(list)) {
    fail("Cannot remove variable declaration: unexpected AST parent.");
  }

  const declarations = Array.from(list.declarations);

  if (declarations.length === 1) {
    const statement = ts.isVariableStatement(list.parent) ? list.parent : list;
    return {
      start: startIncludingLeadingTrivia(statement, sourceFile),
      end: endIncludingTrailingNewline(statement, sourceText),
      reason: "single variable declaration statement",
    };
  }

  return computeCommaListRemoval(node, sourceText, "variable declaration in declaration list");
}

function computeCommaListRemoval(
  node: ts.Node,
  sourceText: string,
  reason: string,
): Removal {
  let start = node.getFullStart();
  let end = node.getEnd();

  const previousComma = findPreviousCommaInSameList(sourceText, start);
  const nextComma = findNextCommaInSameList(sourceText, end);

  if (nextComma !== -1) {
    end = nextComma + 1;
    end = consumeFollowingWhitespaceButNotNewline(sourceText, end);
  } else if (previousComma !== -1) {
    start = previousComma;
    start = consumePreviousWhitespaceButNotNewline(sourceText, start);
  }

  return { start, end, reason };
}

function computeClassMemberRemoval(node: ts.Node, sourceText: string): Removal {
  return {
    start: node.getFullStart(),
    end: endIncludingTrailingNewline(node, sourceText),
    reason: "class member",
  };
}

function findPreviousCommaInSameList(sourceText: string, from: number): number {
  for (let i = from - 1; i >= 0; i--) {
    const ch = sourceText[i];

    if (ch === ",") return i;
    if (ch === "\n" || ch === "\r" || ch === "{" || ch === "[" || ch === "(" || ch === ";") {
      return -1;
    }
  }

  return -1;
}

function findNextCommaInSameList(sourceText: string, from: number): number {
  for (let i = from; i < sourceText.length; i++) {
    const ch = sourceText[i];

    if (ch === ",") return i;
    if (ch === "\n" || ch === "\r" || ch === "}" || ch === "]" || ch === ")" || ch === ";") {
      return -1;
    }
  }

  return -1;
}

function consumeFollowingWhitespaceButNotNewline(sourceText: string, pos: number): number {
  while (pos < sourceText.length && (sourceText[pos] === " " || sourceText[pos] === "\t")) {
    pos++;
  }
  return pos;
}

function consumePreviousWhitespaceButNotNewline(sourceText: string, pos: number): number {
  while (pos > 0 && (sourceText[pos - 1] === " " || sourceText[pos - 1] === "\t")) {
    pos--;
  }
  return pos;
}

function startIncludingLeadingTrivia(node: ts.Node, sourceFile: ts.SourceFile): number {
  return node.getFullStart();
}

function endIncludingTrailingNewline(node: ts.Node, sourceText: string): number {
  let end = node.getEnd();

  while (end < sourceText.length && (sourceText[end] === " " || sourceText[end] === "\t")) {
    end++;
  }

  if (sourceText[end] === "\r" && sourceText[end + 1] === "\n") {
    return end + 2;
  }

  if (sourceText[end] === "\n") {
    return end + 1;
  }

  return end;
}

function locationOf(node: ts.Node): string {
  const sourceFile = node.getSourceFile();
  const pos = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
  return `${sourceFile.fileName}:${pos.line + 1}:${pos.character + 1}`;
}

function fail(message: string): never {
  console.error(message);
  process.exit(1);
}