//
//  ConductHistory.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import {
    Component, mixins, toNative, Watch
} from 'vue-facing-decorator';
import { reactive, computed } from 'vue';
import MixinApplicationSection from '@pages/Applications/_mixins/applicationSection.mixin';
import ApplicationSectionLayout from '@components/ApplicationSectionLayout/ApplicationSectionLayout.vue';
import ApplicationQuestionRow from '@components/ApplicationQuestionRow/ApplicationQuestionRow.vue';
import ApplicationFileList from '@components/ApplicationFileList/ApplicationFileList.vue';
import InputText from '@components/Forms/InputText/InputText.vue';
import InputDate from '@components/Forms/InputDate/InputDate.vue';
import InputTextarea from '@components/Forms/InputTextarea/InputTextarea.vue';
import InputCheckbox from '@components/Forms/InputCheckbox/InputCheckbox.vue';
import InputFile from '@components/Forms/InputFile/InputFile.vue';
import InputButton from '@components/Forms/InputButton/InputButton.vue';
import {
    ApplicationAttestation,
    ApplicationConductConviction,
    ApplicationFile,
    ApplicationSection
} from '@models/Application/Application.model';
import { FormInput } from '@models/FormInput/FormInput.model';
import Joi from 'joi';

export const convictionAttestationId = 'convicted-of-a-criminal-offense';
export const conductConfirmationAttestationId = 'information-true-and-complete';
export const conductExplanationMaxLength = 1000;

export const conductAttestationGroups = [
    {
        key: 'licensureActions',
        titleKey: 'application.licensureActionsTitle',
        attestationIds: [
            'rejected-or-denied-licensure-application',
            'disciplined-by-licensing-board',
            'jurisdiction-limited-practice',
            'publicly-reported-non-disciplinary-action',
            'disciplined-while-holding-professional-license',
            'voluntarily-surrendered-or-restricted-professional-license',
            'disciplinary-action-as-professional',
            'refused-renewal-of-any-professional-license',
        ],
    },
    {
        key: 'legalHistory',
        titleKey: 'application.legalHistoryTitle',
        attestationIds: [
            convictionAttestationId,
            'registered-sex-offender',
        ],
    },
    {
        key: 'currentProceedings',
        titleKey: 'application.currentProceedingsTitle',
        attestationIds: [
            'subject-of-current-proceeding-or-investigation',
            'aided-or-abetted-another-individual-practicing-psychology',
            'practiced-psychology-without-license-or-exemption',
        ],
    },
    {
        key: 'professionalConduct',
        titleKey: 'application.professionalConductTitle',
        attestationIds: [
            'physically-or-mentally-incapable',
            'drugs-or-alcohol-affecting-competency',
            'malpractice-action-or-settlement',
            'action-by-ethics-committee',
            'denied-revoked-suspended-restricted-staff-membership',
            'status-as-provider-revoked-suspended-restricted-by-payor',
            'professional-liability-insurance-canceled',
            'governmental-agency-substantiated-allegations',
        ],
    },
];

interface ConvictionEntry {
    id: number;
    inputs: Record<string, FormInput>;
}

interface AttestationGroup {
    key: string;
    title: string;
    attestations: Array<ApplicationAttestation>;
}

@Component({
    name: 'ConductHistory',
    components: {
        ApplicationSectionLayout,
        ApplicationQuestionRow,
        ApplicationFileList,
        InputText,
        InputDate,
        InputTextarea,
        InputCheckbox,
        InputFile,
        InputButton,
    },
})
class ConductHistory extends mixins(MixinApplicationSection) {
    //
    // Data
    //
    sectionKey = ApplicationSection.CONDUCT_HISTORY;
    convictionEntries: Array<ConvictionEntry> = [];
    convictionCount = 0;
    existingDocuments: Array<ApplicationFile> = [];
    convictionAttestationId = convictionAttestationId;

    //
    // Computed
    //
    get attestations(): Array<ApplicationAttestation> {
        return this.sectionData.attestations || [];
    }

    get questionAttestations(): Array<ApplicationAttestation> {
        return this.attestations.filter((attestation) =>
            attestation.attestationId !== conductConfirmationAttestationId);
    }

    get confirmationAttestation(): ApplicationAttestation | null {
        return this.attestations.find((attestation) =>
            attestation.attestationId === conductConfirmationAttestationId) || null;
    }

    get attestationGroups(): Array<AttestationGroup> {
        const groupedIds = conductAttestationGroups.flatMap((group) => group.attestationIds);
        const ungrouped = this.questionAttestations.filter((attestation) =>
            !groupedIds.includes(attestation.attestationId || ''));

        return conductAttestationGroups.map((group, index) => {
            const isLastGroup = index === conductAttestationGroups.length - 1;
            const attestations = group.attestationIds
                .map((attestationId) => this.questionAttestations.find((attestation) =>
                    attestation.attestationId === attestationId))
                .filter((attestation) => Boolean(attestation)) as Array<ApplicationAttestation>;

            return {
                key: group.key,
                title: this.$t(group.titleKey),
                attestations: (isLastGroup) ? [...attestations, ...ungrouped] : attestations,
            };
        }).filter((group) => group.attestations.length);
    }

    get isConvicted(): boolean {
        return this.formData[`attestation-${convictionAttestationId}`]?.value === true;
    }

    get isAnyYes(): boolean {
        return this.questionAttestations.some((attestation) =>
            this.formData[this.getAttestationKey(attestation)]?.value === true);
    }

    get convictionFormInputs(): Record<string, FormInput> {
        return this.convictionEntries.reduce((inputs, entry) => ({ ...inputs, ...entry.inputs }), {});
    }

    //
    // Methods
    //
    initFormInputs(): void {
        const { sectionData } = this;
        const formData: any = {};

        this.questionAttestations.forEach((attestation) => {
            formData[this.getAttestationKey(attestation)] = this.createAttestationRadioInput(attestation);
        });

        if (this.confirmationAttestation) {
            formData[this.getAttestationKey(this.confirmationAttestation)] = this.createAttestationCheckboxInput(
                this.confirmationAttestation
            );
        }

        formData.notes = new FormInput({
            id: 'conduct-notes',
            name: 'conduct-notes',
            label: computed(() => this.$t('application.explanationLabel')),
            placeholder: computed(() => this.$t('application.explanationPlaceholder')),
            value: sectionData.notes || '',
        });
        formData.documents = this.createFileInput('conduct-documents', this.$t('application.supportingDocumentsTitle'));
        formData.submit = new FormInput({
            isSubmitInput: true,
            id: 'submit-conduct-history',
        });

        this.formData = reactive(formData);
        this.existingDocuments = [...(sectionData.documents || [])];
        this.initConvictionEntries(sectionData.convictions || []);
        this.updateNotesValidation();
        this.watchFormInputs();
    }

    initConvictionEntries(convictions: Array<ApplicationConductConviction>): void {
        this.convictionEntries = [];
        this.convictionCount = 0;
        convictions.forEach((conviction) => this.createConvictionEntry(conviction));
        this.syncConvictionInputs();
    }

    createConvictionEntry(conviction: ApplicationConductConviction = {}): ConvictionEntry {
        const id = this.convictionCount;
        const entry: ConvictionEntry = {
            id,
            inputs: {
                [`convictionCharge${id}`]: new FormInput({
                    id: `conviction-${id}-charge`,
                    name: `conviction-${id}-charge`,
                    label: computed(() => this.$t('application.chargeLabel')),
                    value: conviction.charge || '',
                    validation: this.textValidation(),
                }),
                [`convictionLocation${id}`]: new FormInput({
                    id: `conviction-${id}-location`,
                    name: `conviction-${id}-location`,
                    label: computed(() => this.$t('application.placeOfConvictionLabel')),
                    value: conviction.location || '',
                    validation: this.textValidation(),
                }),
                [`convictionDate${id}`]: new FormInput({
                    id: `conviction-${id}-date`,
                    name: `conviction-${id}-date`,
                    label: computed(() => this.$t('application.convictionDateLabel')),
                    placeholder: 'MM/DD/YYYY',
                    value: conviction.date || '',
                    validation: this.dateValidation(),
                }),
                [`convictionType${id}`]: new FormInput({
                    id: `conviction-${id}-type`,
                    name: `conviction-${id}-type`,
                    label: computed(() => this.$t('application.offenseTypeLabel')),
                    value: conviction.type || '',
                    validation: this.textValidation(),
                }),
            },
        };

        this.convictionCount += 1;
        this.convictionEntries.push(entry);

        return entry;
    }

    convictionInput(entry: ConvictionEntry, field: string): FormInput {
        return entry.inputs[`conviction${field}${entry.id}`];
    }

    syncConvictionInputs(): void {
        if (this.isConvicted && !this.convictionEntries.length) {
            this.createConvictionEntry();
        }

        this.toggleFormInputs(this.convictionFormInputs, this.isConvicted);
    }

    addConviction(): void {
        const entry = this.createConvictionEntry();

        this.toggleFormInputs(entry.inputs, true);
    }

    removeConviction(entry: ConvictionEntry): void {
        this.toggleFormInputs(entry.inputs, false);
        this.convictionEntries = this.convictionEntries.filter((convictionEntry) => convictionEntry.id !== entry.id);
    }

    updateNotesValidation(): void {
        const validation = Joi.string().max(conductExplanationMaxLength);

        this.updateInputValidation(
            this.formData.notes,
            ((this.isAnyYes) ? validation.required() : validation.allow('')).messages(this.joiMessages.string)
        );
    }

    removeExistingDocument(file: ApplicationFile): void {
        this.existingDocuments = this.existingDocuments.filter((document) => document !== file);
        this.updateFormSubmitSuccess('');
    }

    mockPopulate(): void {
        const { formData, confirmationAttestation } = this;

        this.questionAttestations.forEach((attestation) => {
            formData[this.getAttestationKey(attestation)].value = false;
        });

        if (confirmationAttestation) {
            formData[this.getAttestationKey(confirmationAttestation)].value = true;
        }

        formData.notes.value = 'Mock explanation of conduct history.';
    }

    afterClearForm(): void {
        this.toggleFormInputs(this.convictionFormInputs, false);
        this.convictionEntries = [];
        this.convictionCount = 0;
    }

    async prepSectionRequestData(): Promise<object> {
        const { formValues, isConvicted } = this;
        const documents = await this.prepFiles(this.existingDocuments, formValues.documents);

        return {
            attestations: this.prepAttestations(this.attestations),
            convictions: (isConvicted)
                ? this.convictionEntries.map((entry) => ({
                    charge: formValues[`convictionCharge${entry.id}`],
                    location: formValues[`convictionLocation${entry.id}`],
                    date: formValues[`convictionDate${entry.id}`],
                    type: formValues[`convictionType${entry.id}`],
                }))
                : [],
            notes: this.valueOrNull(formValues.notes),
            documents,
        };
    }

    //
    // Watchers
    //
    @Watch('isConvicted') onConvictedChange(): void {
        this.syncConvictionInputs();
    }

    @Watch('isAnyYes') onAnyYesChange(): void {
        this.updateNotesValidation();
    }
}

export default toNative(ConductHistory);

// export default ConductHistory;
