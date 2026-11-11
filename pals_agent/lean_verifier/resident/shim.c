/* Process primitives for the resident Lean worker (see worker.lean.in).
 *
 * Lean's interpreter resolves an `@[extern]` declaration `foo` to the C symbol `l_foo` (or
 * `l_foo___boxed`), so the functions below carry those names.  This file is compiled to a shared
 * library that `lean --load-dynlib` loads before the worker starts; it is not linked into Lean.
 */
#include <lean/lean.h>

/* The verifier image has the Lean toolchain's C compiler but no libc headers, so on Linux the few
 * libc functions used here are declared by hand (the constants are the Linux ones, identical on
 * x86_64 and aarch64).  Other platforms (macOS development) use the system headers. */
#ifdef __linux__
typedef int pid_t_;
typedef void (*handler_t)(int);
struct rlimit_ { unsigned long cur, max; };
extern pid_t_ fork(void);
extern int setpgid(pid_t_, pid_t_);
extern handler_t signal(int, handler_t);
extern void _exit(int);
extern int setrlimit(int, const struct rlimit_ *);
extern int open(const char *, int, ...);
extern long read(int, void *, unsigned long);
extern int close(int);
#define PALS_SIGCHLD 17
#define PALS_RLIMIT_CPU 0
#define PALS_RLIMIT_DATA 2
#define PALS_SIG_IGN ((handler_t)1)
#define PALS_SIG_DFL ((handler_t)0)
#else
#include <signal.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <unistd.h>
#define PALS_SIGCHLD SIGCHLD
#define PALS_SIG_IGN SIG_IGN
#define PALS_SIG_DFL SIG_DFL
#endif

#ifdef __linux__
/* `lean --load-dynlib` opens this library with RTLD_LOCAL, and the interpreter finds `@[extern]`
 * symbols with dlsym(RTLD_DEFAULT): promote the library to the global scope when it is loaded. */
struct dl_info_ { const char *fname; void *fbase; const char *sname; void *saddr; };
extern int dladdr(const void *, struct dl_info_ *);
extern void *dlopen(const char *, int);
__attribute__((constructor)) static void pals_promote(void) {
  struct dl_info_ info;
  if (dladdr((const void *)&pals_promote, &info) && info.fname)
    dlopen(info.fname, 0x2 /* RTLD_NOW */ | 0x100 /* RTLD_GLOBAL */ | 0x4 /* RTLD_NOLOAD */);
}
#endif

static lean_object *ok_unit(void) { return lean_io_result_mk_ok(lean_box(0)); }

/* Parent: finished children are reaped by the kernel (no zombies, no SIGCHLD handling in Lean). */
LEAN_EXPORT lean_object *l_palsInit___boxed(lean_object *u, lean_object *w) {
  (void)u;
  (void)w;
  signal(PALS_SIGCHLD, PALS_SIG_IGN);
  return ok_unit();
}

/* Pure signature on purpose: a `BaseIO UInt32` extern came back with an unrelated value from the
 * interpreter, this form returns the pid.  The argument only keeps calls from being merged. */
LEAN_EXPORT uint32_t l_palsFork(uint64_t n) {
  (void)n;
  return (uint32_t)fork();
}
LEAN_EXPORT lean_object *l_palsFork___boxed(lean_object *n) {
  (void)n;
  return lean_box_uint32((uint32_t)fork());
}

/* Child: own process group (the manager kills the group), default SIGCHLD again, a CPU limit, and
 * on Linux a limit on private writable memory: RLIMIT_DATA counts the heap and private writable
 * mappings but not the read-only mapped .olean files that dominate a Mathlib process.  The limit is
 * what the child already holds plus `budget` bytes. */
LEAN_EXPORT lean_object *l_palsChildSetup___boxed(lean_object *budget, lean_object *cpu, lean_object *w) {
  (void)w;
  uint64_t b = lean_unbox_uint64(budget), c = lean_unbox_uint64(cpu);
  setpgid(0, 0);
  signal(PALS_SIGCHLD, PALS_SIG_DFL);
  /* The worker threads of the zygote do not exist in a forked child, but the task manager still
   * lists them, so every `Task.get` would wait forever.  A new manager (one worker, like
   * `lean --threads=1`) replaces the old pointer; the old one is leaked on purpose (deleting it
   * would try to join threads that are gone).  Calling this twice is not checked by release
   * builds of Lean. */
  lean_init_task_manager_using(1);
#ifdef __linux__
  if (c > 0) {
    struct rlimit_ rl = {c, c};
    setrlimit(PALS_RLIMIT_CPU, &rl);
  }
  if (b > 0) {
    /* VmData of /proc/self/status, in kB */
    char buf[2048];
    unsigned long data_kb = 0;
    int fd = open("/proc/self/status", 0);
    long n = fd >= 0 ? read(fd, buf, sizeof buf - 1) : 0;
    if (fd >= 0) close(fd);
    if (n > 0) {
      buf[n] = 0;
      for (long i = 0; i + 7 < n; i++) {
        if (buf[i] == 'V' && buf[i + 1] == 'm' && buf[i + 2] == 'D' && buf[i + 3] == 'a' &&
            buf[i + 4] == 't' && buf[i + 5] == 'a' && buf[i + 6] == ':') {
          long j = i + 7;
          while (j < n && (buf[j] == ' ' || buf[j] == '\t')) j++;
          while (j < n && buf[j] >= '0' && buf[j] <= '9') data_kb = data_kb * 10 + (buf[j++] - '0');
          break;
        }
      }
    }
    struct rlimit_ rl = {data_kb * 1024 + b, data_kb * 1024 + b};
    setrlimit(PALS_RLIMIT_DATA, &rl);
  }
#else
  if (c > 0) {
    struct rlimit rl = {(rlim_t)c, (rlim_t)c};
    setrlimit(RLIMIT_CPU, &rl);
  }
  (void)b;
#endif
  return ok_unit();
}

/* `_exit`: skip Lean's finalisers, which would try to join task-manager threads that a forked
 * child does not have. */
LEAN_EXPORT lean_object *l_palsExit___boxed(lean_object *code, lean_object *w) {
  (void)w;
  _exit((int)lean_unbox_uint32(code));
  return ok_unit();
}
