"use client";

import { signIn } from "next-auth/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function SignUpPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, password }),
      });
      if (!response.ok) {
        const body = (await response.json()) as { detail?: string };
        setError(body.detail ?? "Registration failed");
        return;
      }
      // account created — sign straight in
      const result = await signIn("credentials", { email, password, redirect: false });
      if (result?.error) {
        setError("Account created, but sign-in failed — try signing in manually");
        return;
      }
      router.push("/talking-head");
      router.refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-sm space-y-8 pt-10">
      <header className="animate-fade-up text-center">
        <h1 className="text-3xl font-semibold tracking-tight">Create account</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          New accounts need admin approval before they can generate.
        </p>
      </header>

      <form
        onSubmit={handleSubmit}
        className="animate-fade-up space-y-4"
        style={{ "--delay": "0.08s" } as React.CSSProperties}
      >
        <div className="space-y-1.5">
          <label
            htmlFor="name"
            className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
          >
            Name
          </label>
          <Input
            id="name"
            autoComplete="name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            disabled={busy}
          />
        </div>
        <div className="space-y-1.5">
          <label
            htmlFor="email"
            className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
          >
            Email
          </label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            disabled={busy}
          />
        </div>
        <div className="space-y-1.5">
          <label
            htmlFor="password"
            className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
          >
            Password
          </label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            minLength={8}
            disabled={busy}
          />
          <p className="text-xs text-muted-foreground/80">At least 8 characters.</p>
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button
          type="submit"
          size="lg"
          className="w-full font-mono uppercase tracking-widest"
          disabled={busy || !name || !email || password.length < 8}
        >
          {busy ? "Creating account…" : "Create account"}
        </Button>
      </form>

      <div
        className="animate-fade-up space-y-4"
        style={{ "--delay": "0.16s" } as React.CSSProperties}
      >
        <div className="flex items-center gap-3">
          <span className="h-px flex-1 bg-border" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            or
          </span>
          <span className="h-px flex-1 bg-border" />
        </div>
        <Button
          variant="secondary"
          size="lg"
          className="w-full font-mono uppercase tracking-widest"
          onClick={() => signIn("google", { callbackUrl: "/talking-head" })}
          disabled={busy}
        >
          Continue with Google
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          Already registered?{" "}
          <Link href="/sign-in" className="text-primary underline-offset-2 hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
