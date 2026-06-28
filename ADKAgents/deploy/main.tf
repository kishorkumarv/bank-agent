terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.29.0"
    }
  }
}

variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID"
}

variable "website_domain" {
  type        = string
  description = "The domain to crawl for the vector search data store (e.g. www.example.com)"
}

variable "member_email" {
  type        = string
  description = "Email of the user or service account to grant IAM roles (e.g. user:you@example.com or serviceAccount:sa@project.iam.gserviceaccount.com)"
}

variable "google_api_key" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Gemini API key passed to the Cloud Run service (optional when using Vertex AI with ADC)"
}

variable "container_image" {
  type        = string
  description = "Fully-qualified container image to deploy (e.g. us-central1-docker.pkg.dev/PROJECT/REPO/agent:latest)"
}

variable "data_store_id" {
  type        = string
  default     = "website-ds"
  description = "ID for the Discovery Engine data store. Auto-incremented by tf-deploy if the previous one is still being deleted."
}

variable "bq_dataset" {
  type        = string
  description = "BigQuery dataset ID containing customer/account/transaction tables"
}

provider "google" {
  project               = var.project_id
  region                = "us-central1"
  user_project_override = true
  billing_project       = var.project_id
}

# 0. Enable required APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "cloudresourcemanager.googleapis.com",
    "discoveryengine.googleapis.com",
    "aiplatform.googleapis.com",
    "run.googleapis.com",
    "bigquery.googleapis.com",
    "iam.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudtrace.googleapis.com",
  ])
  project                    = var.project_id
  service                    = each.value
  disable_on_destroy         = false
}

# 0b. Wait for API propagation before creating dependent resources
resource "time_sleep" "api_propagation" {
  create_duration = "60s"
  depends_on      = [google_project_service.apis]
}

# 0c. Artifact Registry repository for the agent container image
resource "google_artifact_registry_repository" "agent_repo" {
  project       = var.project_id
  location      = "us-central1"
  repository_id = "agent-repo"
  format        = "DOCKER"
  depends_on    = [time_sleep.api_propagation]
}

locals {
  image_url = "us-central1-docker.pkg.dev/${var.project_id}/agent-repo/agent:latest"
}

# 3. Create the Data Store
resource "google_discovery_engine_data_store" "website_datastore" {
  project                     = var.project_id
  location                    = "global"
  data_store_id               = var.data_store_id
  display_name                = var.data_store_id
  industry_vertical           = "GENERIC"
  content_config              = "PUBLIC_WEBSITE"
  solution_types              = ["SOLUTION_TYPE_SEARCH"]
  create_advanced_site_search = false
  depends_on                  = [google_project_service.apis]
}

# 4. Crawl all pages under the domain
resource "google_discovery_engine_target_site" "all_pages" {
  project              = var.project_id
  location             = google_discovery_engine_data_store.website_datastore.location
  data_store_id        = google_discovery_engine_data_store.website_datastore.data_store_id
  provided_uri_pattern = "${var.website_domain}/*"
  type                 = "INCLUDE"
}

# 5. Create the Search AI Application
resource "google_discovery_engine_search_engine" "website_search_app" {
  project        = var.project_id
  location       = google_discovery_engine_data_store.website_datastore.location
  engine_id      = "website-search-app"
  display_name   = "website-search-app"
  data_store_ids = [google_discovery_engine_data_store.website_datastore.data_store_id]
  collection_id  = "default_collection"

  search_engine_config {
    search_tier    = "SEARCH_TIER_ENTERPRISE"
    search_add_ons = ["SEARCH_ADD_ON_LLM"]
  }
}

# 6. IAM — grant the agent's identity the roles it needs
data "google_project" "project" {
  project_id = var.project_id
  depends_on = [google_project_service.apis]
}

locals {
  iam_roles  = [
    "roles/discoveryengine.viewer",
    "roles/aiplatform.user",
    "roles/bigquery.dataViewer",
    "roles/bigquery.jobUser",
  ]
  compute_sa = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "agent_roles" {
  for_each   = toset(local.iam_roles)
  project    = var.project_id
  role       = each.value
  member     = var.member_email
  depends_on = [google_project_service.apis]
}

# Allow Cloud Run's default service account to pull images from Artifact Registry
resource "google_project_iam_member" "cloudrun_artifact_reader" {
  project    = var.project_id
  role       = "roles/artifactregistry.reader"
  member     = local.compute_sa
  depends_on = [google_project_service.apis]
}

# Allow Cloud Run's default service account to query BigQuery
resource "google_project_iam_member" "cloudrun_bq_viewer" {
  project    = var.project_id
  role       = "roles/bigquery.dataViewer"
  member     = local.compute_sa
  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "cloudrun_bq_job_user" {
  project    = var.project_id
  role       = "roles/bigquery.jobUser"
  member     = local.compute_sa
  depends_on = [google_project_service.apis]
}

# Allow Cloud Run's default service account to access Discovery Engine (Vertex Search) and publish traces/metrics
resource "google_project_iam_member" "cloudrun_discoveryengine" {
  project    = var.project_id
  role       = "roles/discoveryengine.viewer"
  member     = local.compute_sa
  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "cloudrun_trace_agent" {
  project    = var.project_id
  role       = "roles/cloudtrace.agent"
  member     = local.compute_sa
  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "cloudrun_metric_writer" {
  project    = var.project_id
  role       = "roles/monitoring.metricWriter"
  member     = local.compute_sa
  depends_on = [google_project_service.apis]
}


# 7. Cloud Run service (only when CONTAINER_IMAGE is set)
resource "google_cloud_run_v2_service" "agent" {
  count               = var.container_image != "" ? 1 : 0
  project             = var.project_id
  name                = "agent-service"
  location            = "us-central1"
  deletion_protection = false

  template {
    containers {
      image = var.container_image

      resources {
        limits = {
          memory = "2Gi"
          cpu    = "1"
        }
      }

      env {
        name  = "GOOGLE_API_KEY"
        value = var.google_api_key
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
      env {
        name  = "VERTEX_DATA_STORE_ID"
        value = google_discovery_engine_search_engine.website_search_app.engine_id
      }
      env {
        name  = "BQ_DATASET"
        value = var.bq_dataset
      }
      env {
        name  = "TRACE_TO_CLOUD"
        value = "true"
      }

      startup_probe {
        http_get {
          path = "/"
          port = 8080
        }
        initial_delay_seconds = 10
        period_seconds        = 10
        timeout_seconds       = 5
        failure_threshold     = 29
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.container_image != "" ? 1 : 0
  project  = google_cloud_run_v2_service.agent[0].project
  location = google_cloud_run_v2_service.agent[0].location
  name     = google_cloud_run_v2_service.agent[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Output the Engine ID — use this as VERTEX_DATA_STORE_ID in your .env
output "vertex_data_store_id" {
  description = "Set this as VERTEX_DATA_STORE_ID in bank_agent/.env"
  value       = google_discovery_engine_search_engine.website_search_app.engine_id
}

output "image_url" {
  description = "Fully-qualified container image URL to use as CONTAINER_IMAGE"
  value       = local.image_url
}

output "cloud_run_url" {
  description = "Public URL of the deployed agent"
  value       = var.container_image != "" ? google_cloud_run_v2_service.agent[0].uri : "(no container image set)"
}
