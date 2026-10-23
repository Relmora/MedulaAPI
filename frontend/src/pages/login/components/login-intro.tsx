import { Layers3 } from "lucide-react";

export function LoginIntro() {
  return (
    <section className="relative hidden overflow-hidden bg-stone-950 p-12 text-white lg:flex lg:flex-col lg:justify-between">
      <div className="flex items-center gap-3 text-xl font-medium tracking-[-0.02em]">
        <span className="rounded-xl bg-white/10 p-2">
          <Layers3 className="size-5" aria-hidden="true" />
        </span>
        MedulaAPI
      </div>

      <div className="relative z-10 max-w-xl">
        <p className="mb-5 text-xs font-medium tracking-[0.24em] text-teal-300 uppercase">
          Your knowledge, organized
        </p>
        <h1 className="text-5xl leading-[1.08] font-normal tracking-[-0.04em] xl:text-[3.5rem]">
          Turn scattered information into useful knowledge.
        </h1>
        <p className="mt-7 max-w-md text-lg leading-8 font-light text-stone-400">
          Build focused workspaces, organize knowledge bases, and keep the
          context your team needs in one place.
        </p>
      </div>

      <p className="text-sm font-light tracking-wide text-stone-500">
        One workspace at a time. One source of truth.
      </p>

      <div
        className="pointer-events-none absolute -right-52 -bottom-52 size-[38rem] rounded-full border border-white/10"
        aria-hidden="true"
      >
        <div className="m-20 size-[calc(100%-10rem)] rounded-full border border-white/10">
          <div className="m-20 size-[calc(100%-10rem)] rounded-full border border-white/10" />
        </div>
      </div>
    </section>
  );
}
