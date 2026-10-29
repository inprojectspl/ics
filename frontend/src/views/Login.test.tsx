import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { setLocale } from "../lib/i18n";
import { Login } from "./Login";

const authConfig = vi.fn();
const login = vi.fn();
const assign = vi.fn();
const originalLocation = window.location;

vi.mock("../api", () => ({
  api: {
    authConfig: (...a: unknown[]) => authConfig(...a),
    login: (...a: unknown[]) => login(...a),
  },
}));

function fill() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret123" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

beforeEach(() => {
  assign.mockReset();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, assign },
  });
  authConfig.mockReset().mockResolvedValue({
    google_oidc_enabled: false,
    self_register_enabled: false,
  });
  login.mockReset();
});

afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
});

describe("Login", () => {
  it("logs in with the typed credentials and reports success", async () => {
    login.mockResolvedValue({ ok: true });
    const onLogged = vi.fn();
    render(<Login onLogged={onLogged} />);
    await waitFor(() => expect(authConfig).toHaveBeenCalled());
    fill();
    await waitFor(() => expect(onLogged).toHaveBeenCalledTimes(1));
    expect(login).toHaveBeenCalledWith("a@example.com", "secret123");
  });

  it("shows an error and stays on the form when login fails", async () => {
    login.mockRejectedValue(new Error("401"));
    const onLogged = vi.fn();
    render(<Login onLogged={onLogged} />);
    fill();
    expect(await screen.findByText("Wrong email or password")).toBeInTheDocument();
    expect(onLogged).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign in" })).not.toBeDisabled();
  });

  it("offers Google sign-in and self-registration when the config enables them", async () => {
    authConfig.mockResolvedValue({ google_oidc_enabled: true, self_register_enabled: true });
    render(<Login onLogged={vi.fn()} />);
    const google = await screen.findByRole("link", { name: /Sign in with Google/ });
    expect(google).toHaveAttribute("href", "/api/auth/google/login");
    expect(screen.getByRole("link", { name: "Create an account" })).toBeInTheDocument();
  });

  it("navigates to the backend consent endpoint after a successful password login", async () => {
    login.mockResolvedValue({ ok: true });
    const onLogged = vi.fn();
    const next = "/api/auth/oauth/authorize?client_id=chatgpt&state=a%2Bb&scope=ics";
    render(<Login onLogged={onLogged} next={next} />);
    fill();
    await waitFor(() => expect(assign).toHaveBeenCalledWith(next));
    expect(onLogged).not.toHaveBeenCalled();
  });

  it("passes the full return path to the Google flow", async () => {
    authConfig.mockResolvedValue({ google_oidc_enabled: true });
    const next = "/api/auth/oauth/authorize?state=a%2Bb&resource=https%3A%2F%2Fmcp.example";
    render(<Login onLogged={vi.fn()} next={next} />);
    const google = await screen.findByRole("link", { name: /Sign in with Google/ });
    expect(google).toHaveAttribute("href", `/api/auth/google/login?next=${encodeURIComponent(next)}`);
  });

  it("ignores an external return for both login methods", async () => {
    authConfig.mockResolvedValue({ google_oidc_enabled: true });
    login.mockResolvedValue({ ok: true });
    const onLogged = vi.fn();
    render(<Login onLogged={onLogged} next="https://evil.example/" />);
    const google = await screen.findByRole("link", { name: /Sign in with Google/ });
    expect(google).toHaveAttribute("href", "/api/auth/google/login");
    fill();
    await waitFor(() => expect(onLogged).toHaveBeenCalled());
    expect(assign).not.toHaveBeenCalled();
  });

  it("falls back to the plain form when the config request fails", async () => {
    authConfig.mockRejectedValue(new Error("down"));
    render(<Login onLogged={vi.fn()} />);
    await waitFor(() => expect(authConfig).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: /Google/ })).not.toBeInTheDocument();
    expect(screen.getByText("No account? Ask an admin.")).toBeInTheDocument();
  });

  it("shows Google sign-in once the config answers after a failed attempt", async () => {
    // A request lost while the server restarts must not hide Google until a reload.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      authConfig
        .mockRejectedValueOnce(new Error("502"))
        .mockResolvedValue({ google_oidc_enabled: true, self_register_enabled: false });
      render(<Login onLogged={vi.fn()} />);
      await waitFor(() => expect(authConfig).toHaveBeenCalledTimes(1));
      expect(screen.queryByRole("link", { name: /Google/ })).not.toBeInTheDocument();

      await vi.advanceTimersByTimeAsync(1000);

      expect(await screen.findByRole("link", { name: /Sign in with Google/ })).toBeInTheDocument();
      expect(authConfig).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders in Polish and reports a failed login in Polish", async () => {
    setLocale("pl", { persist: false });
    login.mockRejectedValue(new Error("401"));
    render(<Login onLogged={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Zaloguj się" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Nie pamiętasz hasła?" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: "a@example.com" } });
    fireEvent.change(screen.getByLabelText("Hasło"), { target: { value: "secret123" } });
    fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));
    expect(await screen.findByText("Nieprawidłowy e-mail lub hasło")).toBeInTheDocument();
  });
});
