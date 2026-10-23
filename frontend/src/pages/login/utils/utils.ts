import { z } from "zod";
import { login, register, type Credentials } from "@/services/auth";

export type FormState = Credentials & { validation: string };

export type LoginFormProps = {
  isPending: boolean;
  sessionError: unknown;
  onRetry: () => void;
};

class FormValidationError extends Error {}

const loginSchema = z.object({
  username: z.string().trim().toLowerCase().min(1, "Enter your username."),
  password: z
    .string()
    .min(1, "Enter your password.")
    .max(128, "Password must be no more than 128 characters."),
});

const registrationSchema = z.object({
  username: z
    .string()
    .trim()
    .toLowerCase()
    .min(3, "Username must contain at least 3 characters.")
    .max(64, "Username must contain no more than 64 characters.")
    .regex(
      /^[a-z0-9_.-]+$/,
      "Username can only contain letters, numbers, _, . or -.",
    ),
  password: z
    .string()
    .min(15, "Password must contain at least 15 characters.")
    .max(128, "Password must contain no more than 128 characters."),
});

function validateCredentials(
  credentials: Credentials,
  creatingAccount: boolean,
): Credentials {
  const result = (
    creatingAccount ? registrationSchema : loginSchema
  ).safeParse(credentials);

  if (!result.success) {
    throw new FormValidationError(result.error.issues[0].message);
  }

  return result.data;
}

export function authenticate(
  credentials: Credentials,
  creatingAccount: boolean,
) {
  const validatedCredentials = validateCredentials(
    credentials,
    creatingAccount,
  );

  return creatingAccount
    ? register(validatedCredentials)
    : login(validatedCredentials);
}
