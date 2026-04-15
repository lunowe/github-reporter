import type { RepoConnection } from "~/types/api";

export interface AvailableRepo {
  full_name: string;
  name: string;
  description: string;
  private: boolean;
  default_branch: string;
  owner: string;
  updated_at: string;
}

interface AvailableReposResponse {
  repos: AvailableRepo[];
  install_url: string;
  installed: boolean;
}

/**
 * Repo management composable.
 */
export function useRepos() {
  const { apiFetch } = useApi();

  const repos = useState<RepoConnection[]>("repos", () => []);
  const loading = ref(false);

  // Available repos from GitHub
  const availableRepos = useState<AvailableRepo[]>("availableRepos", () => []);
  const availableLoading = ref(false);
  const appInstalled = useState<boolean>("appInstalled", () => true);
  const installUrl = useState<string>("installUrl", () => "");

  async function fetchRepos() {
    loading.value = true;
    try {
      repos.value = await apiFetch<RepoConnection[]>("/api/repos");
    } catch (e) {
      console.error("Failed to fetch repos:", e);
    } finally {
      loading.value = false;
    }
  }

  async function fetchAvailableRepos() {
    availableLoading.value = true;
    try {
      const data = await apiFetch<AvailableReposResponse>(
        "/api/repos/available"
      );
      availableRepos.value = data.repos;
      appInstalled.value = data.installed;
      installUrl.value = data.install_url;
    } catch (e) {
      console.error("Failed to fetch available repos:", e);
    } finally {
      availableLoading.value = false;
    }
  }

  async function addRepo(
    repoFullName: string,
    displayName?: string,
    defaultBranch?: string
  ) {
    const result = await apiFetch<RepoConnection>("/api/repos", {
      method: "POST",
      body: {
        repo_full_name: repoFullName,
        display_name: displayName,
        default_branch: defaultBranch || "main",
      },
    });
    repos.value.push(result);
    return result;
  }

  async function deleteRepo(repoId: string) {
    await apiFetch(`/api/repos/${repoId}`, { method: "DELETE" });
    repos.value = repos.value.filter((r) => r.id !== repoId);
  }

  return {
    repos,
    loading,
    availableRepos,
    availableLoading,
    appInstalled,
    installUrl,
    fetchRepos,
    fetchAvailableRepos,
    addRepo,
    deleteRepo,
  };
}
