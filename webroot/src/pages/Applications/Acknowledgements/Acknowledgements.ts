//
//  Acknowledgements.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import { Component, mixins, toNative } from 'vue-facing-decorator';
import { reactive, computed } from 'vue';
import MixinApplicationSection from '@pages/Applications/_mixins/applicationSection.mixin';
import ApplicationSectionLayout from '@components/ApplicationSectionLayout/ApplicationSectionLayout.vue';
import ApplicationQuestionRow from '@components/ApplicationQuestionRow/ApplicationQuestionRow.vue';
import InputText from '@components/Forms/InputText/InputText.vue';
import InputCheckbox from '@components/Forms/InputCheckbox/InputCheckbox.vue';
import { ApplicationAttestation, ApplicationSection } from '@models/Application/Application.model';
import { FormInput } from '@models/FormInput/FormInput.model';

export const signAndSubmitAttestationId = 'sign-and-submit';
export const factualAttestationId = 'information-presented-is-factual';

@Component({
    name: 'Acknowledgements',
    components: {
        ApplicationSectionLayout,
        ApplicationQuestionRow,
        InputText,
        InputCheckbox,
    },
})
class Acknowledgements extends mixins(MixinApplicationSection) {
    //
    // Data
    //
    sectionKey = ApplicationSection.ACKNOWLEDGEMENTS;

    //
    // Computed
    //
    get attestations(): Array<ApplicationAttestation> {
        return this.sectionData.attestations || [];
    }

    get statementAttestations(): Array<ApplicationAttestation> {
        return this.attestations.filter((attestation) =>
            ![signAndSubmitAttestationId, factualAttestationId].includes(attestation.attestationId || ''));
    }

    get signAndSubmitAttestation(): ApplicationAttestation | null {
        return this.attestations.find((attestation) =>
            attestation.attestationId === signAndSubmitAttestationId) || null;
    }

    get factualAttestation(): ApplicationAttestation | null {
        return this.attestations.find((attestation) => attestation.attestationId === factualAttestationId) || null;
    }

    //
    // Methods
    //
    initFormInputs(): void {
        const formData: any = {};

        this.statementAttestations.forEach((attestation) => {
            formData[this.getAttestationKey(attestation)] = this.createAttestationRadioInput(attestation, {
                mustBeTrue: true,
            });
        });

        if (this.factualAttestation) {
            formData[this.getAttestationKey(this.factualAttestation)] = this.createAttestationCheckboxInput(
                this.factualAttestation
            );
        }

        formData.signatureName = new FormInput({
            id: 'signature-name',
            name: 'signature-name',
            label: computed(() => this.$t('application.signatureNameLabel')),
            autocomplete: 'name',
            value: this.sectionData.signatureName || '',
            validation: this.textValidation(),
        });
        formData.submit = new FormInput({
            isSubmitInput: true,
            id: 'submit-acknowledgements',
        });

        this.formData = reactive(formData);
        this.watchFormInputs();
    }

    mockPopulate(): void {
        const { formData, factualAttestation } = this;

        this.statementAttestations.forEach((attestation) => {
            formData[this.getAttestationKey(attestation)].value = true;
        });

        if (factualAttestation) {
            formData[this.getAttestationKey(factualAttestation)].value = true;
        }

        formData.signatureName.value = 'Test Applicant';
    }

    prepSectionRequestData(): object {
        return {
            attestations: this.prepAttestations(this.attestations),
            signatureName: this.formValues.signatureName,
        };
    }
}

export default toNative(Acknowledgements);

// export default Acknowledgements;
