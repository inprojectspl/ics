import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAssetUpload } from "./useAssetUpload";

vi.mock("../api", () => ({
  api: {
    uploadMarkdown: vi.fn().mockResolvedValue({}),
    uploadCollection: vi.fn().mockResolvedValue({}),
    uploadHtmlBundle: vi.fn().mockResolvedValue({}),
    uploadPdf: vi.fn().mockResolvedValue({}),
    uploadDocument: vi.fn().mockResolvedValue({}),
  },
}));
const { toast } = vi.hoisted(() => ({ toast: vi.fn() }));
vi.mock("../components/Toast", () => ({ useToast: () => ({ toast }) }));

const { api } = await import("../api");

// Array-like stand-in for a FileList (the hook only does Array.from + .length).
function asFileList(...files: File[]): FileList {
  const obj: Record<number, File> & { length: number } = { length: files.length };
  files.forEach((f, i) => (obj[i] = f));
  return obj as unknown as FileList;
}

beforeEach(() => vi.clearAllMocks());

describe("useAssetUpload", () => {
  it("threads projectId through to uploadMarkdown when uploading into a project", async () => {
    const onUploaded = vi.fn();
    const { result } = renderHook(() =>
      useAssetUpload({ uploadMode: "org_sso", projectId: "proj-1", onUploaded }),
    );
    const file = new File(["# hi"], "doc.md", { type: "text/markdown" });
    await act(async () => {
      await result.current.onPicked(asFileList(file));
    });
    expect(api.uploadMarkdown).toHaveBeenCalledWith(file, "org_sso", "proj-1");
    expect(onUploaded).toHaveBeenCalled();
  });

  it("omits projectId on the home dashboard (undefined)", async () => {
    const onUploaded = vi.fn();
    const { result } = renderHook(() =>
      useAssetUpload({ uploadMode: "public", onUploaded }),
    );
    const file = new File(["# hi"], "doc.md");
    await act(async () => {
      await result.current.onPicked(asFileList(file));
    });
    expect(api.uploadMarkdown).toHaveBeenCalledWith(file, "public", undefined);
  });

  it("routes a .pdf file to uploadPdf", async () => {
    const onUploaded = vi.fn();
    const { result } = renderHook(() =>
      useAssetUpload({ uploadMode: "org_sso", projectId: "proj-1", onUploaded }),
    );
    const file = new File(["%PDF-1.7"], "Report.PDF", { type: "application/pdf" });
    await act(async () => {
      await result.current.onPicked(asFileList(file));
    });
    expect(api.uploadPdf).toHaveBeenCalledWith(file, "org_sso", "proj-1");
    expect(api.uploadMarkdown).not.toHaveBeenCalled();
    expect(onUploaded).toHaveBeenCalled();
  });

  it("uploads a .md and a .pdf picked together as two documents", async () => {
    const { result } = renderHook(() =>
      useAssetUpload({ uploadMode: "public", onUploaded: vi.fn() }),
    );
    const md = new File(["# hi"], "a.md");
    const pdf = new File(["%PDF"], "b.pdf");
    await act(async () => {
      await result.current.onPicked(asFileList(md, pdf));
    });
    expect(api.uploadMarkdown).toHaveBeenCalledWith(md, "public", undefined);
    expect(api.uploadPdf).toHaveBeenCalledWith(pdf, "public", undefined);
    expect(api.uploadCollection).not.toHaveBeenCalled();
  });

  it.each(["Contract.docx", "notes.ODT", "old.doc"])(
    "routes %s to uploadDocument",
    async (name) => {
      const onUploaded = vi.fn();
      const { result } = renderHook(() =>
        useAssetUpload({ uploadMode: "org_sso", projectId: "proj-1", onUploaded }),
      );
      const file = new File(["PK"], name);
      await act(async () => {
        await result.current.onPicked(asFileList(file));
      });
      expect(api.uploadDocument).toHaveBeenCalledWith(file, "org_sso", "proj-1");
      expect(api.uploadMarkdown).not.toHaveBeenCalled();
      expect(api.uploadPdf).not.toHaveBeenCalled();
      expect(onUploaded).toHaveBeenCalled();
    },
  );

  it("uploads a .docx dropped next to a .md as two documents, not a collection", async () => {
    const { result } = renderHook(() =>
      useAssetUpload({ uploadMode: "public", onUploaded: vi.fn() }),
    );
    const md = new File(["# hi"], "a.md");
    const docx = new File(["PK"], "b.docx");
    await act(async () => {
      await result.current.onPicked(asFileList(md, docx));
    });
    expect(api.uploadMarkdown).toHaveBeenCalledWith(md, "public", undefined);
    expect(api.uploadDocument).toHaveBeenCalledWith(docx, "public", undefined);
    expect(api.uploadCollection).not.toHaveBeenCalled();
  });

  it("skips a file of an unsupported type", async () => {
    const { result } = renderHook(() =>
      useAssetUpload({ uploadMode: "org_sso", onUploaded: vi.fn() }),
    );
    await act(async () => {
      await result.current.onPicked(asFileList(new File(["x"], "sheet.xlsx")));
    });
    expect(api.uploadMarkdown).not.toHaveBeenCalled();
    expect(api.uploadPdf).not.toHaveBeenCalled();
    expect(api.uploadDocument).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("sheet.xlsx"), "info");
  });

  it("ignores an empty pick without calling the API", async () => {
    const onUploaded = vi.fn();
    const { result } = renderHook(() =>
      useAssetUpload({ uploadMode: "org_sso", onUploaded }),
    );
    await act(async () => {
      await result.current.onPicked(asFileList());
    });
    expect(api.uploadMarkdown).not.toHaveBeenCalled();
    expect(onUploaded).not.toHaveBeenCalled();
  });
});
