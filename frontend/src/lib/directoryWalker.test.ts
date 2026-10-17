import { describe, it, expect } from "vitest";
import {
  isCollectionDrop,
  isHtmlBundleDrop,
  walkDataTransfer,
  type WalkedFile,
} from "./directoryWalker";

function file(path: string): WalkedFile {
  return { file: new File([""], path.split("/").pop() || "x"), path };
}

// Minimal FileSystemEntry mocks for walkDataTransfer.

function fileEntry(name: string): FileSystemFileEntry {
  return {
    isFile: true,
    isDirectory: false,
    name,
    file: (resolve: (f: File) => void) => resolve(new File([""], name)),
  } as unknown as FileSystemFileEntry;
}

function dirEntry(name: string, children: FileSystemEntry[]): FileSystemDirectoryEntry {
  return {
    isFile: false,
    isDirectory: true,
    name,
    createReader: () => {
      // Spec: readEntries yields batches until empty. Drain in one batch,
      // then signal end with an empty array.
      let drained = false;
      return {
        readEntries: (resolve: (e: FileSystemEntry[]) => void) => {
          if (drained) return resolve([]);
          drained = true;
          resolve(children);
        },
      } as FileSystemDirectoryReader;
    },
  } as unknown as FileSystemDirectoryEntry;
}

function itemList(entries: (FileSystemEntry | null)[]): DataTransferItemList {
  return entries.map((e) => ({
    webkitGetAsEntry: () => e,
  })) as unknown as DataTransferItemList;
}

describe("walkDataTransfer", () => {
  it("returns [] for an empty drop", async () => {
    expect(await walkDataTransfer(itemList([]))).toEqual([]);
  });

  it("skips items without an entry (webkitGetAsEntry returns null)", async () => {
    expect(await walkDataTransfer(itemList([null]))).toEqual([]);
  });

  it("returns a single file with a root path", async () => {
    const out = await walkDataTransfer(itemList([fileEntry("a.md")]));
    expect(out.map((w) => w.path)).toEqual(["a.md"]);
    expect(out[0]?.file).toBeInstanceOf(File);
  });

  it("recursively flattens nested directories into POSIX paths", async () => {
    const tree = dirEntry("Vault", [
      fileEntry("root.md"),
      dirEntry("Notes", [fileEntry("page.md")]),
    ]);
    const out = await walkDataTransfer(itemList([tree]));
    expect(out.map((w) => w.path).sort()).toEqual([
      "Vault/Notes/page.md",
      "Vault/root.md",
    ]);
  });

  it("ignores an entry that is neither a file nor a directory", async () => {
    const weird = { isFile: false, isDirectory: false, name: "?" } as FileSystemEntry;
    expect(await walkDataTransfer(itemList([weird]))).toEqual([]);
  });
});

describe("isCollectionDrop", () => {
  it("returns false for an empty drop", () => {
    expect(isCollectionDrop([])).toBe(false);
  });

  it("returns false for a single file", () => {
    expect(isCollectionDrop([file("readme.md")])).toBe(false);
  });

  it("returns true for 2 or more .md files at the root", () => {
    expect(
      isCollectionDrop([file("a.md"), file("b.md")]),
    ).toBe(true);
  });

  it("returns true for a nested structure", () => {
    expect(
      isCollectionDrop([file("Vault/a.md"), file("Vault/b.md")]),
    ).toBe(true);
  });

  it("returns true for one file in a directory (nesting)", () => {
    // At least one nested path makes a collection.
    expect(
      isCollectionDrop([file("Vault/a.md"), file("Vault/notes/b.md")]),
    ).toBe(true);
  });

  it("returns false for 2 files with only one .md", () => {
    expect(
      isCollectionDrop([file("readme.md"), file("image.png")]),
    ).toBe(false);
  });
});

describe("isHtmlBundleDrop", () => {
  it("returns true for an .html file", () => {
    expect(isHtmlBundleDrop([file("index.html")])).toBe(true);
  });

  it("returns true for an .htm file (legacy)", () => {
    expect(isHtmlBundleDrop([file("page.htm")])).toBe(true);
  });

  it("ignores the extension case", () => {
    expect(isHtmlBundleDrop([file("INDEX.HTML")])).toBe(true);
  });

  it("returns true for mixed md+html: html wins", () => {
    expect(
      isHtmlBundleDrop([file("README.md"), file("index.html")]),
    ).toBe(true);
  });

  it("returns false for Markdown only", () => {
    expect(
      isHtmlBundleDrop([file("readme.md"), file("notes.md")]),
    ).toBe(false);
  });
});
