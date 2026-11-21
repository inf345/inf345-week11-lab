# The Docker daemon on this machine. WHERE it is (a Unix socket, a Windows
# named pipe, DOCKER_HOST) is a fact about your machine, so it is not written here.
provider "docker" {}

resource "docker_image" "app" {
  name         = var.image
  platform     = "linux/amd64" # what your CI builds (Week 6); Apple-silicon Macs emulate it
  keep_locally = true          # destroy removes the container, not the downloaded image
}

resource "docker_network" "app" {
  name = "inf345-net"
}

resource "docker_container" "app" {
  name = "inf345-app"
  # BLANK 5 - a REFERENCE to the image resource's ID (resource type . name . attribute).
  # This one line tells Terraform: the image first, then the container.
  image   = ____
  restart = var.restart_policy
  env     = ["PORT=${var.internal_port}"]

  ports {
    # BLANK 6 - the port the app listens on INSIDE the container (look at the env line)
    internal = ____
    external = var.host_port
  }

  networks_advanced {
    # BLANK 7 - a REFERENCE to the network resource's name
    name = ____
  }
}
