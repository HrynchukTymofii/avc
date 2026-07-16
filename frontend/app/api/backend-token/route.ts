import { SignJWT } from "jose";
import { getServerSession } from "next-auth";
import { NextResponse } from "next/server";

import { authOptions } from "@/lib/auth-config";

const TOKEN_TTL_S = 30 * 60;

/** Mints a short-lived HS256 JWT for the FastAPI backend from the NextAuth
 * session. The backend verifies it with the same API_JWT_SECRET — this is the
 * only bridge between the two auth worlds. */
export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session?.user?.userId) {
    return NextResponse.json({ detail: "Not signed in" }, { status: 401 });
  }

  const secret = process.env.API_JWT_SECRET;
  if (!secret) {
    return NextResponse.json(
      { detail: "API_JWT_SECRET is not configured" },
      { status: 500 },
    );
  }

  const token = await new SignJWT({
    email: session.user.email,
    name: session.user.name,
    approved: session.user.approved,
    role: session.user.role,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(session.user.userId)
    .setIssuedAt()
    .setExpirationTime(`${TOKEN_TTL_S}s`)
    .sign(new TextEncoder().encode(secret));

  return NextResponse.json({ token, expiresIn: TOKEN_TTL_S });
}
