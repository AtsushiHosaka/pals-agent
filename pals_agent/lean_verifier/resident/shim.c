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
extern int prctl(int, ...);
extern long syscall(long, ...);
extern char *getenv(const char *);
extern void *dlopen(const char *, int);
extern void *dlsym(void *, const char *);
extern int dprintf(int, const char *, ...);
#define PALS_SIGCHLD 17
#define PALS_RLIMIT_FSIZE 1
#define PALS_RLIMIT_CORE 4
#define PALS_RLIMIT_NOFILE 7
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


#ifdef __linux__
/* ------------------------------------------------------------------ confinement (Linux)
 * Zygote: no new privileges, Landlock (read on the runtime, write on the request root and its own
 * scratch), no socket/signal/ptrace syscalls.  Child, on top of that: write and read only under
 * its own request directory plus the runtime, and no way to create another process: no fork,
 * vfork, exec, setsid, setpgid and clone only for threads.  A request therefore cannot reach
 * another request's files, kill the zygote or leave a descendant behind.  Anything that fails
 * while confining ends the process (fail closed). */
#define LL_EXECUTE (1ULL << 0)
#define LL_WRITE_FILE (1ULL << 1)
#define LL_READ_FILE (1ULL << 2)
#define LL_READ_DIR (1ULL << 3)
#define LL_TRUNCATE (1ULL << 14)
#define LL_READ (LL_READ_FILE | LL_READ_DIR | LL_EXECUTE)
#define LL_FILE_BITS (LL_EXECUTE | LL_WRITE_FILE | LL_READ_FILE | LL_TRUNCATE)
#define PALS_O_PATH 010000000
#define PALS_O_CLOEXEC 02000000

struct ll_attr { uint64_t handled; };
struct ll_rule { uint64_t allowed; int32_t parent_fd; } __attribute__((packed));

static int g_confine = 0;
static char g_roots[8192];
static char g_request_root[1024];
static char g_scratch[1024];
static void *g_seccomp_zygote = 0, *g_seccomp_child = 0;
static void *g_lib = 0;

static uint64_t ll_handled_all(void) {
  long abi = syscall(444, 0, 0, 1);
  if (abi < 1) return 0;
  uint64_t m = (1ULL << 13) - 1;
  if (abi >= 2) m |= 1ULL << 13;
  if (abi >= 3) m |= 1ULL << 14;
  return m;
}

static int ll_add(int ruleset, const char *path, uint64_t access, uint64_t handled) {
  int p = open(path, PALS_O_PATH | PALS_O_CLOEXEC);
  if (p < 0) return 0; /* a root that does not exist grants nothing */
  struct ll_rule r = {access & handled, p};
  long rc = syscall(445, ruleset, 1, &r, 0);
  if (rc != 0) { /* a file cannot carry directory-only rights */
    r.allowed = access & handled & LL_FILE_BITS;
    rc = syscall(445, ruleset, 1, &r, 0);
  }
  close(p);
  return rc == 0 ? 0 : -1;
}

static int ll_roots(int ruleset, uint64_t handled, int child) {
  char buf[sizeof g_roots];
  int n = 0;
  for (; g_roots[n] && n < (int)sizeof buf - 1; n++) buf[n] = g_roots[n];
  buf[n] = 0;
  char *start = buf;
  for (char *c = buf;; c++) {
    if (*c == ':' || *c == 0) {
      char end = *c;
      *c = 0;
      /* a child may read its own /proc/self, not the process files of any other request */
      const char *root = (child && start[0] == '/' && start[1] == 'p' && start[2] == 'r' &&
                          start[3] == 'o' && start[4] == 'c' && start[5] == 0)
                             ? "/proc/self" : start;
      if (*start && ll_add(ruleset, root, LL_READ, handled) != 0) return -1;
      if (!end) break;
      start = c + 1;
    }
  }
  return 0;
}

static int ll_confine(const char *write_dir, int zygote) {
  uint64_t handled = ll_handled_all();
  if (!handled) return -1;
  struct ll_attr attr = {handled};
  int rs = (int)syscall(444, &attr, sizeof attr, 0);
  if (rs < 0) return -1;
  int bad = ll_roots(rs, handled, !zygote);
  uint64_t all = handled; /* every right, including reading, on a directory it owns */
  if (!bad && ll_add(rs, "/dev/null", LL_READ_FILE | LL_WRITE_FILE, handled)) bad = 1;
  if (!bad && ll_add(rs, "/dev/urandom", LL_READ_FILE, handled)) bad = 1;
  if (!bad && zygote && g_request_root[0] && ll_add(rs, g_request_root, all, handled)) bad = 1;
  if (!bad && zygote && g_scratch[0] && ll_add(rs, g_scratch, all, handled)) bad = 1;
  if (!bad && write_dir && write_dir[0] && ll_add(rs, write_dir, all, handled)) bad = 1;
  if (!bad && syscall(446, rs, 0) != 0) bad = 1;
  close(rs);
  return bad ? -1 : 0;
}

typedef void *(*sc_init_t)(uint32_t);
typedef int (*sc_resolve_t)(const char *);
typedef int (*sc_add_t)(void *, uint32_t, int, unsigned, ...);
typedef int (*sc_load_t)(void *);
struct sc_cmp { unsigned arg; int op; uint64_t a, b; };
typedef int (*sc_add1_t)(void *, uint32_t, int, unsigned, struct sc_cmp);
#define SC_ALLOW 0x7fff0000u
#define SC_ERRNO(e) (0x00050000u | (e))
#define SC_MASKED_EQ 7

static void *sc_build(const char *const *names, int clone_threads_only, int owner_fcntl) {
  sc_init_t init = (sc_init_t)dlsym(g_lib, "seccomp_init");
  sc_resolve_t resolve = (sc_resolve_t)dlsym(g_lib, "seccomp_syscall_resolve_name");
  sc_add_t add = (sc_add_t)dlsym(g_lib, "seccomp_rule_add");
  sc_add1_t add1 = (sc_add1_t)dlsym(g_lib, "seccomp_rule_add");
  if (!init || !resolve || !add || !add1) return 0;
  void *ctx = init(SC_ALLOW);
  if (!ctx) return 0;
  for (int i = 0; names[i]; i++) {
    int nr = resolve(names[i]);
    if (nr < 0) continue; /* not on this architecture (fork on aarch64) */
    if (add(ctx, SC_ERRNO(1), nr, 0) != 0) return 0;
  }
  if (clone_threads_only) {
    int clone_nr = resolve("clone");
    struct sc_cmp not_thread = {0, SC_MASKED_EQ, 0x00010000ULL, 0}; /* CLONE_THREAD unset */
    if (clone_nr >= 0 && add1(ctx, SC_ERRNO(1), clone_nr, 1, not_thread) != 0) return 0;
    int clone3_nr = resolve("clone3");
    if (clone3_nr >= 0 && add(ctx, SC_ERRNO(38), clone3_nr, 0) != 0) return 0; /* ENOSYS */
  }
  if (owner_fcntl) {
    int fcntl_nr = resolve("fcntl");
    for (int k = 0; k < 3; k++) {
      static const uint64_t cmds[3] = {8, 10, 15}; /* F_SETOWN, F_SETSIG, F_SETOWN_EX */
      struct sc_cmp c = {1, SC_MASKED_EQ, 0xffffffffULL, cmds[k]};
      if (fcntl_nr >= 0 && add1(ctx, SC_ERRNO(1), fcntl_nr, 1, c) != 0) return 0;
    }
  }
  return ctx;
}

static void confine_init(void) {
  const char *flag = getenv("PALS_RESIDENT_CONFINE");
  if (!flag || flag[0] != '1') return;
  g_confine = 1;
  const char *roots = getenv("PALS_RESIDENT_READ_ROOTS");
  const char *request = getenv("PALS_RESIDENT_REQUEST_ROOT");
  const char *scratch = getenv("TMPDIR");
  for (int i = 0; roots && roots[i] && i < (int)sizeof g_roots - 1; i++) g_roots[i] = roots[i];
  for (int i = 0; request && request[i] && i < (int)sizeof g_request_root - 1; i++)
    g_request_root[i] = request[i];
  for (int i = 0; scratch && scratch[i] && i < (int)sizeof g_scratch - 1; i++)
    g_scratch[i] = scratch[i];
  g_lib = dlopen("libseccomp.so.2", 2 /* RTLD_NOW */);
  static const char *const zy[] = {"socket", "socketpair", "connect", "bind", "listen", "accept",
    "accept4", "sendto", "sendmsg", "sendmmsg", "recvfrom", "recvmsg", "recvmmsg", "kill", "tkill",
    "tgkill", "rt_sigqueueinfo", "rt_tgsigqueueinfo", "pidfd_send_signal", "ptrace",
    "process_vm_readv", "process_vm_writev", 0};
  static const char *const ch[] = {"fork", "vfork", "execve", "execveat", "setsid", "setpgid", 0};
  if (g_lib) {
    g_seccomp_zygote = sc_build(zy, 0, 1);
    g_seccomp_child = sc_build(ch, 1, 0);
  }
  if (!g_seccomp_zygote || !g_seccomp_child || prctl(38, 1, 0, 0, 0) != 0 ||
      ll_confine(0, 1) != 0 || ((sc_load_t)dlsym(g_lib, "seccomp_load"))(g_seccomp_zygote) != 0) {
    dprintf(2, "resident confinement could not be established\n");
    _exit(72);
  }
}

static void confine_child(const char *write_dir) {
  if (!g_confine) return;
  if (ll_confine(write_dir, 0) != 0 ||
      ((sc_load_t)dlsym(g_lib, "seccomp_load"))(g_seccomp_child) != 0)
    _exit(71);
}
#endif

static lean_object *ok_unit(void) { return lean_io_result_mk_ok(lean_box(0)); }

/* Parent: finished children are reaped by the kernel (no zombies, no SIGCHLD handling in Lean). */
LEAN_EXPORT lean_object *l_palsInit___boxed(lean_object *u, lean_object *w) {
  (void)u;
  (void)w;
  signal(PALS_SIGCHLD, PALS_SIG_IGN);
#ifdef __linux__
  confine_init();
#endif
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
LEAN_EXPORT lean_object *l_palsChildSetup___boxed(lean_object *budget, lean_object *cpu,
                                                  lean_object *fsize, lean_object *dir,
                                                  lean_object *w) {
  (void)w;
  uint64_t b = lean_unbox_uint64(budget), c = lean_unbox_uint64(cpu);
  uint64_t f = lean_unbox_uint64(fsize);
  const char *write_dir = lean_string_cstr(dir);
  setpgid(0, 0);
  signal(PALS_SIGCHLD, PALS_SIG_DFL);
  /* The worker threads of the zygote do not exist in a forked child, but the task manager still
   * lists them, so every `Task.get` would wait forever.  A new manager (one worker, like
   * `lean --threads=1`) replaces the old pointer; the old one is leaked on purpose (deleting it
   * would try to join threads that are gone).  Calling this twice is not checked by release
   * builds of Lean. */
  lean_init_task_manager_using(1);
#ifdef __linux__
  prctl(1, 9); /* PR_SET_PDEATHSIG, SIGKILL: a request child never outlives its zygote */
  {
    struct rlimit_ core = {0, 0}, nofile = {1024, 1024};
    setrlimit(PALS_RLIMIT_CORE, &core);
    setrlimit(PALS_RLIMIT_NOFILE, &nofile);
    if (f > 0) {
      struct rlimit_ fs = {f, f};
      setrlimit(PALS_RLIMIT_FSIZE, &fs);
    }
  }
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
  confine_child(write_dir);
#else
  if (c > 0) {
    struct rlimit rl = {(rlim_t)c, (rlim_t)c};
    setrlimit(RLIMIT_CPU, &rl);
  }
  (void)b;
  (void)f;
  (void)write_dir;
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
