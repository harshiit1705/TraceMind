export interface ProjectItem {
  id: string;
  name: string;
  slug: string;
  environment: string;
  description?: string | null;
  is_demo: boolean;
  organization_id?: string;
  created_at?: string;
  updated_at?: string;
}

