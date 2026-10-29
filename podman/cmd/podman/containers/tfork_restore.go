package containers

import (
	"fmt"

	"github.com/containers/podman/v5/cmd/podman/common"
	"github.com/containers/podman/v5/cmd/podman/registry"
	"github.com/containers/podman/v5/pkg/domain/entities"
	"github.com/spf13/cobra"
)

var (
	tforkRestoreDescription = `Creates a new container from the persistent image of a live clone made with
  'podman container clone --live --persistent'. The clone may be running or stopped.`

	containerTforkRestoreCommand = &cobra.Command{
		Use:               "tfork-restore [options] CLONE",
		Short:             "Restore a new container from a persistent tfork clone image",
		Long:              tforkRestoreDescription,
		RunE:              tforkRestore,
		Args:              cobra.ExactArgs(1),
		ValidArgsFunction: common.AutocompleteContainers,
		Example:           `podman container tfork-restore --name restored my-clone`,
	}
)

var tforkRestoreOpts entities.ContainerTforkRestoreOptions

func init() {
	registry.Commands = append(registry.Commands, registry.CliCommand{
		Command: containerTforkRestoreCommand,
		Parent:  containerCmd,
	})
	flags := containerTforkRestoreCommand.Flags()
	flags.StringVar(&tforkRestoreOpts.Name, "name", "", "name of the restored container (default: CLONE-restored)")
}

func tforkRestore(_ *cobra.Command, args []string) error {
	rep, err := registry.ContainerEngine().ContainerTforkRestore(registry.Context(), args[0], tforkRestoreOpts)
	if err != nil {
		return err
	}
	fmt.Println(rep.Id)
	return nil
}
