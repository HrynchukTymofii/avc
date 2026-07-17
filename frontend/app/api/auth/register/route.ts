import bcrypt from "bcryptjs";
import { NextResponse } from "next/server";

import { db } from "@/lib/db";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Email/password registration. New accounts start with 100 credits
 * (User.credits default); the backend prices jobs against that allowance. */
export async function POST(request: Request) {
  let body: { name?: string; email?: string; password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 });
  }

  const name = body.name?.trim() || "";
  const email = body.email?.trim().toLowerCase() || "";
  const password = body.password ?? "";

  if (!name || name.length > 80) {
    return NextResponse.json({ detail: "Please enter your name" }, { status: 422 });
  }
  if (!EMAIL_RE.test(email)) {
    return NextResponse.json({ detail: "Please enter a valid email" }, { status: 422 });
  }
  if (password.length < 8) {
    return NextResponse.json(
      { detail: "Password must be at least 8 characters" },
      { status: 422 },
    );
  }

  const existing = await db.user.findUnique({ where: { email } });
  if (existing) {
    return NextResponse.json(
      { detail: "An account with this email already exists" },
      { status: 409 },
    );
  }

  await db.user.create({
    data: {
      name,
      email,
      password: await bcrypt.hash(password, 10),
      emailVerified: new Date(), // no OTP flow (yet) — treat as verified
    },
  });

  return NextResponse.json({ ok: true });
}
