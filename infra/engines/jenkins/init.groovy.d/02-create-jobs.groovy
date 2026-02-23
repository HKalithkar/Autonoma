import jenkins.model.Jenkins
import hudson.model.FreeStyleProject

Jenkins instance = Jenkins.get()

def jobNames = [
  "dummy-build",
  "dummy-test",
  "dummy-deploy",
  "dummy-backup",
]

jobNames.each { name ->
  if (instance.getItem(name) == null) {
    FreeStyleProject job = instance.createProject(FreeStyleProject, name)
    job.setDescription("Autonoma dummy job: ${name}")
    job.save()
  }
}

instance.save()
