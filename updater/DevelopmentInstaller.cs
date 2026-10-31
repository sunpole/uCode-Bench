// Isolated GitHub prerelease channel; never replaces stable binaries or user data.
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace UCode.Updater;

internal static class DevelopmentInstaller
{
    private const string Base = "https://github.com/sunpole/uCode-Bench";
    private static readonly Uri Releases = new("https://api.github.com/repos/sunpole/uCode-Bench/releases?per_page=30");
    private static readonly Regex ShaPattern = new("^[a-f0-9]{40}$", RegexOptions.CultureInvariant | RegexOptions.Compiled);
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private sealed record Candidate(string sha, string tag, string filename, string packageUrl, long size);
    private sealed record State(string current, string? previous);

    internal static string InstallRoot => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "uBrand", "uCode-Dev");

    internal static bool IsSha(string value) => value.Length == 40 && ShaPattern.IsMatch(value);

    private static string StatePath => Path.Combine(InstallRoot, "development-state.json");

    private static State? ReadState()
    {
        if (!File.Exists(StatePath)) return null;
        var state = JsonSerializer.Deserialize<State>(File.ReadAllText(StatePath, Encoding.UTF8));
        if (state is null || !IsSha(state.current) || (state.previous is not null && !IsSha(state.previous)))
            throw new InvalidDataException("Повреждена запись управляемой Development-версии.");
        return state;
    }

    private static void SaveState(State state)
    {
        string temp = StatePath + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(temp, JsonSerializer.Serialize(state, JsonOptions), new UTF8Encoding(false));
            File.Move(temp, StatePath, overwrite: true);
        }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }

    private static string VersionPath(string sha) =>
        IsSha(sha) ? Path.Combine(InstallRoot, "versions", "dev-" + sha)
                   : throw new InvalidDataException("Недопустимый идентификатор версии.");
    private static string Binary(string sha) => Path.Combine(VersionPath(sha), "uCode", "uCode.exe");

    private static async Task<Candidate?> LatestAsync()
    {
        byte[] payload = await SafeInstaller.DownloadBytes(Releases, 2 * 1024 * 1024);
        using JsonDocument doc = JsonDocument.Parse(payload);
        if (doc.RootElement.ValueKind != JsonValueKind.Array) throw new InvalidDataException("GitHub вернул не список релизов.");
        foreach (JsonElement release in doc.RootElement.EnumerateArray())
        {
            if (release.ValueKind != JsonValueKind.Object ||
                release.GetProperty("draft").GetBoolean() ||
                !release.GetProperty("prerelease").GetBoolean()) continue;
            string tag = release.GetProperty("tag_name").GetString() ?? "";
            if (!tag.StartsWith("dev-", StringComparison.Ordinal) || !IsSha(tag[4..])) continue;
            if (release.GetProperty("html_url").GetString() != Base + "/releases/tag/" + tag)
                throw new InvalidDataException("Ссылка Development-релиза недействительна.");
            string sha = tag[4..];
            string name = "uCode-dev-" + sha[..12] + "-windows-x64.zip";
            string baseUrl = Base + "/releases/download/" + tag + "/";
            long size = -1;
            bool manifest = false, checksums = false;
            foreach (JsonElement asset in release.GetProperty("assets").EnumerateArray())
            {
                string assetName = asset.GetProperty("name").GetString() ?? "";
                string link = asset.GetProperty("browser_download_url").GetString() ?? "";
                if (assetName == name && link == baseUrl + name)
                    size = asset.GetProperty("size").GetInt64();
                if (assetName == "development.json" && link == baseUrl + "development.json") manifest = true;
                if (assetName == "SHA256SUMS.txt" && link == baseUrl + "SHA256SUMS.txt") checksums = true;
            }
            if (size > 1024 && size <= 512L * 1024 * 1024 && manifest && checksums)
                return new Candidate(sha, tag, name, baseUrl + name, size);
        }
        return null;
    }

    internal static async Task<object> CheckAsync(string currentSha)
    {
        if (!IsSha(currentSha)) throw new FormatException("Неверный SHA текущей Development-сборки.");
        Candidate? candidate = await LatestAsync();
        return new
        {
            application = "uCode",
            channel = "development",
            installed_commit = currentSha,
            latest_commit = candidate?.sha,
            status = candidate is null ? "NO_PUBLISHED_BUILD" :
                candidate.sha == currentSha ? "CURRENT" : "UPDATE_AVAILABLE",
            platform = "windows-x64",
            package = candidate is null ? null : new
            {
                name = candidate.filename, url = candidate.packageUrl, size_bytes = candidate.size
            },
            release_url = candidate is null ? null : Base + "/releases/tag/" + candidate.tag,
            installation = candidate is not null && candidate.sha != currentSha ?
                "AVAILABLE_WITH_CONFIRMATION" : "NOT_APPLICABLE",
            checked_with = "uCode.Updater.exe 0.3.0"
        };
    }

    private static async Task<(Candidate, byte[])> VerifiedPackageAsync(string currentSha)
    {
        Candidate? release = await LatestAsync();
        if (release is null || release.sha == currentSha)
            throw new InvalidOperationException("Новой проверенной Development-сборки нет.");
        string baseUrl = Base + "/releases/download/" + release.tag + "/";
        string manifest = Encoding.UTF8.GetString(
            await SafeInstaller.DownloadBytes(new Uri(baseUrl + "SHA256SUMS.txt"), 32 * 1024));
        string hash = SafeInstaller.ExpectedHash(manifest, release.filename);
        byte[] info = await SafeInstaller.DownloadBytes(new Uri(baseUrl + "development.json"), 32 * 1024);
        using JsonDocument metadata = JsonDocument.Parse(info);
        JsonElement data = metadata.RootElement;
        if (data.GetProperty("schema").GetInt32() != 1 ||
            data.GetProperty("application").GetString() != "uCode" ||
            data.GetProperty("channel").GetString() != "development" ||
            data.GetProperty("source_commit").GetString() != release.sha ||
            data.GetProperty("tag").GetString() != release.tag ||
            data.GetProperty("package").GetString() != release.filename ||
            data.GetProperty("platform").GetString() != "windows-x64" ||
            data.GetProperty("sha256").GetString() != hash ||
            data.GetProperty("size_bytes").GetInt64() != release.size)
            throw new InvalidDataException("Манифест Development не соответствует опубликованному пакету.");
        Console.WriteLine("STAGE:downloading-package");
        byte[] bytes = await SafeInstaller.DownloadBytes(new Uri(release.packageUrl), 512L * 1024 * 1024);
        Console.WriteLine("STAGE:verifying-sha256");
        if (bytes.LongLength != release.size ||
            !CryptographicOperations.FixedTimeEquals(SHA256.HashData(bytes), Convert.FromHexString(hash)))
            throw new InvalidDataException("Development ZIP не прошёл контроль SHA-256.");
        return (release, bytes);
    }

    internal static async Task<int> InstallAsync(string currentSha, bool accepted)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if (!accepted) throw new InvalidOperationException("Необходимо явное подтверждение пользователя.");
        if (!IsSha(currentSha)) throw new FormatException("Некорректный SHA.");
        SafeInstaller.RequireNoLinks(InstallRoot);
        Directory.CreateDirectory(InstallRoot);
        using var gate = new FileStream(Path.Combine(InstallRoot, "installer.lock"),
            FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        Console.WriteLine("STAGE:checking-release");
        State? old = ReadState();
        var (release, zip) = await VerifiedPackageAsync(currentSha);
        if (old is not null && old.current == release.sha)
            throw new InvalidOperationException("Эта Development-сборка уже установлена.");
        string target = VersionPath(release.sha);
        if (Directory.Exists(target)) throw new IOException("Целевая версия уже существует; установка отменена.");
        Directory.CreateDirectory(Path.Combine(InstallRoot, "versions"));
        string stage = Path.Combine(InstallRoot, ".stage-" + Guid.NewGuid().ToString("N"));
        try
        {
            Console.WriteLine("STAGE:extracting");
            SafeInstaller.ExtractSafe(zip, stage);
            string[] infos = Directory.GetFiles(Path.Combine(stage, "uCode"),
                "build-info.json", SearchOption.AllDirectories);
            if (infos.Length != 1) throw new InvalidDataException("Не найдена единственная build-info.json.");
            using (JsonDocument info = JsonDocument.Parse(File.ReadAllBytes(infos[0])))
                if (info.RootElement.GetProperty("channel").GetString() != "development" ||
                    info.RootElement.GetProperty("commit").GetString() != release.sha)
                    throw new InvalidDataException("Версия внутри EXE не совпадает с Development-релизом.");
            Console.WriteLine("STAGE:smoke-test");
            SafeInstaller.Smoke(Path.Combine(stage, "uCode", "uCode.exe"));
            Directory.Move(stage, target);
            string persistent = Path.Combine(InstallRoot, "uCode.Updater.exe");
            if (!File.Exists(persistent))
            {
                string host = Environment.ProcessPath ?? "";
                if (!Path.GetFileName(host).Equals("uCode.Updater.exe", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Неизвестный исполняемый файл updater.");
                File.Copy(host, persistent, overwrite: false);
            }
            SaveState(new State(release.sha, old?.current));
            Console.WriteLine("STAGE:installed");
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                status = "INSTALLED", channel = "development", commit = release.sha,
                previous = old?.current, launcher = persistent
            }, JsonOptions));
            return 0;
        }
        finally { if (Directory.Exists(stage)) Directory.Delete(stage, recursive: true); }
    }

    internal static int Launch()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        SafeInstaller.RequireNoLinks(InstallRoot);
        State state = ReadState() ?? throw new InvalidDataException("Отсутствует Development-установка.");
        string exe = Binary(state.current);
        SafeInstaller.RequireNoLinks(exe);
        if (!File.Exists(exe))
        {
            if (state.previous is null || !File.Exists(Binary(state.previous)))
                throw new InvalidDataException("Нет доступной предыдущей версии для отката.");
            SaveState(new State(state.previous, state.current));
            exe = Binary(state.previous);
            SafeInstaller.RequireNoLinks(exe);
        }
        Process.Start(new ProcessStartInfo(exe)
        {
            WorkingDirectory = Path.GetDirectoryName(exe)!, UseShellExecute = false
        });
        return 0;
    }

    internal static int Rollback(bool accepted)
    {
        if (!OperatingSystem.IsWindows() || !accepted) throw new InvalidOperationException("Откат требует Windows и подтверждения.");
        SafeInstaller.RequireNoLinks(InstallRoot);
        using var gate = new FileStream(Path.Combine(InstallRoot, "installer.lock"),
            FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        State state = ReadState() ?? throw new InvalidDataException("Нет управляемой Development-установки.");
        if (state.previous is null || !File.Exists(Binary(state.previous)))
            throw new InvalidDataException("Предыдущая версия отсутствует.");
        SaveState(new State(state.previous, state.current));
        Console.WriteLine("DEV_ROLLBACK_OK " + state.previous);
        return 0;
    }

    internal static bool SelfTest()
    {
        if (!IsSha(new string('a', 40)) || IsSha("../traversal") || IsSha(new string('G', 40)))
            return false;
        string filename = "uCode-dev-" + new string('a', 12) + "-windows-x64.zip";
        return filename == "uCode-dev-aaaaaaaaaaaa-windows-x64.zip";
    }
}
